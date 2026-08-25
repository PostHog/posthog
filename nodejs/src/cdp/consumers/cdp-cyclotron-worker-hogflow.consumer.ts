import { DateTime } from 'luxon'

import { HogFlow } from '~/cdp/schema/hogflow'
import { instrumented } from '~/common/tracing/tracing-utils'
import { logger } from '~/common/utils/logger'
import { PluginsServerConfig } from '~/types'

import { isRowScopedTrigger } from '../schema/hogflow'
import { JobQueue } from '../services/job-queue/job-queue.interface'
import { CyclotronJobInvocation, CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '../types'
import { convertToHogFunctionFilterGlobal } from '../utils/hog-function-filtering'
import { createInvocationResult } from '../utils/invocation-utils'
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

    /**
     * Terminate an invocation as canceled through the normal result pipeline, so the
     * terminal lifecycle row, app metric, and run log all land. A bare cyclotron
     * status flip would leave the run showing 'running' in the Invocations UI forever.
     */
    private buildCanceledResult(
        item: CyclotronJobInvocation,
        message: string,
        hogFlow?: HogFlow
    ): CyclotronJobInvocationResult {
        // The monitoring services identify a workflow result by the presence of `hogFlow`, and use
        // it to key the terminal lifecycle row as `hog_flow` and to fill the row's trigger fields.
        // Without it the row keys as `hog_function`; because `function_kind` is part of the
        // ReplacingMergeTree key, that row could never collapse the `running` row (written as
        // `hog_flow`), leaving the run stuck at 'running' in the Invocations tab. When the live flow
        // is gone (deleted, or its lookup failed) we still know its id, which is `item.functionId`,
        // so attach a minimal stub carrying just that so the row still keys as `hog_flow`. Only `id`
        // is read off this object on the cancellation path.
        const resolvedFlow = hogFlow ?? ({ id: item.functionId } as HogFlow)
        const invocation = { ...item, hogFlow: resolvedFlow }
        const result = createInvocationResult(invocation, {}, { finished: true })
        result.canceled = true
        result.logs.push({ level: 'info', timestamp: DateTime.now(), message })
        result.metrics.push({
            team_id: item.teamId,
            app_source_id: item.parentRunId ?? item.functionId,
            instance_id: (item.state as CyclotronJobInvocationHogFlow['state'] | null)?.currentAction?.id,
            metric_kind: 'other',
            metric_name: 'canceled',
            count: 1,
        })
        return result
    }

    @instrumented('cdpConsumer.handleEachBatch.loadHogFlows')
    protected async loadHogFlows(invocations: CyclotronJobInvocation[]): Promise<LoadHogFlowsResult> {
        const loadedInvocations: CyclotronJobInvocationHogFlow[] = []
        const failedInvocations: CyclotronJobInvocation[] = []
        const canceledResults: CyclotronJobInvocationResult[] = []

        await Promise.all(
            invocations.map(async (item) => {
                // Checked before the team/flow lookups so a cancel-requested run terminates even
                // when its flow or team has since been deleted. The flow lookup here is
                // best-effort and only sets the terminal row's function_kind: a null flow
                // (deleted) or a lookup error still cancels.
                if (item.cancelRequestedAt) {
                    const hogFlow = await this.hogFlowManager.getHogFlow(item.functionId).catch(() => null)
                    canceledResults.push(this.buildCanceledResult(item, 'Run canceled', hogFlow ?? undefined))
                    return
                }

                const team = await this.deps.teamManager.getTeam(item.teamId)
                const hogFlow = await this.hogFlowManager.getHogFlow(item.functionId)
                if (!hogFlow || !team) {
                    logger.error('⚠️', 'Error finding hog flow', {
                        id: item.functionId,
                    })

                    failedInvocations.push(item)

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
                        this.buildCanceledResult(item, 'Run canceled: the workflow is no longer active', hogFlow)
                    )

                    return
                }

                const hogFlowInvocationState = item.state as CyclotronJobInvocationHogFlow['state']

                // Warehouse-row invocations don't have a real person — the row is the unit of work
                // and person-dependent steps no-op for these flows. Explicitly skip the person lookup
                // rather than relying on event.distinct_id being empty so future changes to the
                // synthetic event shape don't accidentally re-enable the lookup.
                const isWarehouseRow = isRowScopedTrigger(hogFlow.trigger)
                // Account-audience batch invocations carry the account's group key as
                // event.distinct_id; resolving it as a person distinct_id would attach an
                // unrelated person to the run. Accounts have no person — skip the lookup.
                // The state stamp wins over the live trigger, which may have been edited to a
                // person audience while these children were queued; the trigger check remains
                // as a fallback for jobs enqueued before the stamp existed.
                const isAccountAudience =
                    hogFlowInvocationState.accountAudience === true ||
                    (hogFlow.trigger?.type === 'batch' && hogFlow.trigger.filters?.audience_type === 'accounts')
                // The matcher wrote this job's personId anchor: a merge repointed the distinct_id onto a
                // survivor, or the distinct_id acquired its first person. Resolve by that personId so the step
                // reads the right person — resolving by the distinct_id would hit its stale ~1min cache entry
                // (the pre-merge person, or none at all) and e.g. drop an email.
                const resolveByRepointedPerson =
                    hogFlowInvocationState.personIdRepointed === true && !!hogFlowInvocationState.personId
                // One-shot: consume the flag on this wake-resolution only. Later steps fall back to normal
                // distinct_id-first resolution, which self-heals to the latest survivor if the distinct_id is
                // repointed again (a second merge onto a non-wait step is out of processMoveBatch's scope).
                if (resolveByRepointedPerson) {
                    delete hogFlowInvocationState.personIdRepointed
                }
                const personIdOrDistinctId =
                    isWarehouseRow || isAccountAudience
                        ? undefined
                        : resolveByRepointedPerson
                          ? hogFlowInvocationState.personId
                          : hogFlowInvocationState.event.distinct_id || hogFlowInvocationState.personId
                const kind =
                    resolveByRepointedPerson || !hogFlowInvocationState.event.distinct_id ? 'person_id' : 'distinct_id'

                const [person, groups] = await Promise.all([
                    personIdOrDistinctId
                        ? this.personsManager.getCyclotronPerson(hogFlow.team_id, personIdOrDistinctId, kind)
                        : undefined,
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
                    person: person ?? undefined,
                    groups,
                    variables: hogFlowInvocationState.variables || {},
                })

                const loaded: CyclotronJobInvocationHogFlow = {
                    ...item,
                    state: hogFlowInvocationState,
                    hogFlow,
                    person: person ?? undefined,
                    groups,
                    filterGlobals,
                }

                if (personIdOrDistinctId) {
                    loaded.refreshPerson = async () => {
                        const fresh = await this.personsManager.getCyclotronPerson(
                            hogFlow.team_id,
                            personIdOrDistinctId,
                            kind,
                            { forceFresh: true }
                        )
                        return {
                            person: fresh ?? undefined,
                            filterGlobals: convertToHogFunctionFilterGlobal({
                                event: hogFlowInvocationState.event,
                                person: fresh ?? undefined,
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
