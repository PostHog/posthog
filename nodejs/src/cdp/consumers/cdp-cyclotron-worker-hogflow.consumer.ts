import { HogFlow } from '~/cdp/schema/hogflow'
import {
    hogFlowPersonLookup,
    loadHogFlowPerson,
    resolvesByRepointedPerson,
} from '~/cdp/services/hogflows/hogflow-person'
import { applyPendingWake } from '~/cdp/services/hogflows/pending-wake'
import { instrumented } from '~/common/tracing/tracing-utils'
import { logger } from '~/common/utils/logger'
import { PluginsServerConfig } from '~/types'

import { JobQueue } from '../services/job-queue/job-queue.interface'
import { CyclotronJobInvocation, CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '../types'
import { convertToHogFunctionFilterGlobal } from '../utils/hog-function-filtering'
import { createCanceledInvocationResult } from '../utils/invocation-utils'
import { CdpConsumerBaseDeps } from './cdp-base.consumer'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

type LoadHogFlowsResult = {
    loadedInvocations: CyclotronJobInvocationHogFlow[]
    canceledResults: CyclotronJobInvocationResult[]
}

export class CdpCyclotronWorkerHogFlow extends CdpCyclotronWorker {
    protected override name = 'CdpCyclotronWorkerHogFlow'

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps, jobQueue: JobQueue) {
        super(config, deps, jobQueue, 'hogflow')
    }

    @instrumented('cdpConsumer.handleEachBatch.executeInvocations')
    public override async processInvocations(
        invocations: CyclotronJobInvocation[]
    ): Promise<CyclotronJobInvocationResult[]> {
        const { loadedInvocations, canceledResults } = await this.loadHogFlows(invocations)
        const executed = await Promise.all(loadedInvocations.map((item) => this.hogFlowExecutor.execute(item)))
        return [...canceledResults, ...executed]
    }

    protected async hogFlowsFor(invocations: CyclotronJobInvocation[]): Promise<Record<HogFlow['id'], HogFlow | null>> {
        return await this.hogFlowManager.getHogFlowsCheckingPrimaryOnMiss(invocations.map((item) => item.functionId))
    }

    @instrumented('cdpConsumer.handleEachBatch.loadHogFlows')
    protected async loadHogFlows(invocations: CyclotronJobInvocation[]): Promise<LoadHogFlowsResult> {
        const loadedInvocations: CyclotronJobInvocationHogFlow[] = []
        const failedInvocations: CyclotronJobInvocation[] = []
        const canceledResults: CyclotronJobInvocationResult[] = []
        const hogFlows = await this.hogFlowsFor(invocations.filter((item) => !item.cancelRequestedAt))

        await Promise.all(
            invocations.map(async (item) => {
                // Checked before the team/flow lookups so a cancel-requested run terminates even
                // when its flow or team has since been deleted. The flow lookup here is
                // best-effort and only sets the terminal row's function_kind: a null flow
                // (deleted) or a lookup error still cancels.
                if (item.cancelRequestedAt) {
                    const hogFlow = await this.hogFlowManager.getHogFlow(item.functionId).catch(() => null)
                    canceledResults.push(createCanceledInvocationResult(item, 'Run canceled', hogFlow ?? undefined))
                    return
                }

                const team = await this.deps.teamManager.getTeam(item.teamId)
                const hogFlow = hogFlows[item.functionId]
                if (!hogFlow || !team) {
                    logger.error('⚠️', 'Error finding hog flow', {
                        id: item.functionId,
                    })

                    failedInvocations.push(item)
                    this.invocationResultsService.emailStatusService.queueUnavailableRun(item)

                    return
                }

                // A run waking while its workflow is disabled/archived is canceled rather
                // than executed. Runs that wake while the workflow is active proceed
                // normally, so re-enabling before a parked run's wake time releases it.
                if (hogFlow.status !== 'active') {
                    logger.info('⏭️', 'Cancelling hog flow invocation - workflow is no longer active', {
                        id: item.functionId,
                        status: hogFlow.status,
                    })

                    canceledResults.push(
                        createCanceledInvocationResult(item, 'Run canceled: the workflow is no longer active', hogFlow)
                    )

                    return
                }

                const hogFlowInvocationState = item.state as CyclotronJobInvocationHogFlow['state']
                applyPendingWake(hogFlowInvocationState, item.pendingWake)

                const personLookup = hogFlowPersonLookup(hogFlow, hogFlowInvocationState)
                // One-shot: consume the flag on this wake-resolution only. Later steps fall back to normal
                // distinct_id-first resolution, which self-heals to the latest survivor if the distinct_id is
                // repointed again (a second merge onto a non-wait step is out of processMoveBatch's scope).
                if (resolvesByRepointedPerson(hogFlowInvocationState)) {
                    delete hogFlowInvocationState.personIdRepointed
                }
                const [person, groups] = await Promise.all([
                    personLookup ? loadHogFlowPerson(this.personsManager, hogFlow, personLookup) : undefined,
                    this.groupsManager.getGroupsForEvent(
                        hogFlow.team_id,
                        hogFlowInvocationState.event.properties,
                        `${this.config.SITE_URL}/project/${hogFlow.team_id}`
                    ),
                ])

                if (!person && hogFlow.trigger?.type === 'event') {
                    logger.warn('⚠️', 'Person not found for hog flow invocation', {
                        hogFlowId: hogFlow.id,
                        distinctId: hogFlowInvocationState.event?.distinct_id || hogFlowInvocationState.personId,
                        invocationId: item.id,
                    })
                }

                // Batch-triggered invocations arrive with an empty event.distinct_id because the
                // blast-radius query returns UUIDs only. The person lookup above resolves one
                // distinct_id for us (when the person has any), so backfill it here so templates
                // defaulting to `{event.distinct_id}` resolve at hog runtime.
                if (!hogFlowInvocationState.event.distinct_id && person?.distinct_id) {
                    hogFlowInvocationState.event.distinct_id = person.distinct_id
                }

                // Persist the resolved person UUID into state so a re-parked wait keeps its person_id
                // even when a later re-resolution transiently misses. clickhouse_person wakes match on
                // person_id only, so a wait parked with person_id = null could never be woken by a
                // person-property change — it would depend entirely on the polling backstop.
                if (person?.id && !hogFlowInvocationState.personId) {
                    hogFlowInvocationState.personId = person.id
                }

                const filterGlobals = convertToHogFunctionFilterGlobal({
                    event: hogFlowInvocationState.event,
                    person,
                    groups,
                    variables: hogFlowInvocationState.variables || {},
                })

                const loaded: CyclotronJobInvocationHogFlow = {
                    ...item,
                    state: hogFlowInvocationState,
                    hogFlow,
                    person,
                    groups,
                    filterGlobals,
                }

                if (personLookup) {
                    loaded.refreshPerson = async () => {
                        const fresh = await loadHogFlowPerson(this.personsManager, hogFlow, {
                            ...personLookup,
                            forceFresh: true,
                        })
                        return {
                            person: fresh,
                            filterGlobals: convertToHogFunctionFilterGlobal({
                                event: hogFlowInvocationState.event,
                                person: fresh,
                                groups,
                                variables: hogFlowInvocationState.variables || {},
                            }),
                        }
                    }
                }

                loadedInvocations.push(loaded)
            })
        )

        await this.cyclotronJobQueue.dequeueInvocations(failedInvocations)

        return { loadedInvocations, canceledResults }
    }
}
