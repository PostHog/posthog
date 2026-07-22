import { instrumented } from '~/common/tracing/tracing-utils'
import { logger } from '~/common/utils/logger'
import { PluginsServerConfig } from '~/types'

import { JobQueue } from '../services/job-queue/job-queue.interface'
import { CyclotronJobInvocation, CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '../types'
import { convertToHogFunctionFilterGlobal } from '../utils/hog-function-filtering'
import { CdpConsumerBaseDeps } from './cdp-base.consumer'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

export class CdpCyclotronWorkerHogFlow extends CdpCyclotronWorker {
    protected override name = 'CdpCyclotronWorkerHogFlow'

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps, jobQueue: JobQueue) {
        super(config, deps, jobQueue, 'hogflow')
    }

    @instrumented('cdpConsumer.handleEachBatch.executeInvocations')
    public override async processInvocations(
        invocations: CyclotronJobInvocation[]
    ): Promise<CyclotronJobInvocationResult[]> {
        const loadedInvocations = await this.loadHogFlows(invocations)
        return await Promise.all(loadedInvocations.map((item) => this.hogFlowExecutor.execute(item)))
    }

    @instrumented('cdpConsumer.handleEachBatch.loadHogFlows')
    protected async loadHogFlows(invocations: CyclotronJobInvocation[]): Promise<CyclotronJobInvocationHogFlow[]> {
        const loadedInvocations: CyclotronJobInvocationHogFlow[] = []
        const failedInvocations: CyclotronJobInvocation[] = []
        const skippedInvocations: CyclotronJobInvocation[] = []

        await Promise.all(
            invocations.map(async (item) => {
                const team = await this.deps.teamManager.getTeam(item.teamId)
                const hogFlow = await this.hogFlowManager.getHogFlow(item.functionId)
                if (!hogFlow || !team) {
                    logger.error('⚠️', 'Error finding hog flow', {
                        id: item.functionId,
                    })

                    failedInvocations.push(item)

                    return
                }

                // Skip execution if the workflow is no longer active (e.g., disabled/archived)
                if (hogFlow.status !== 'active') {
                    logger.info('⏭️', 'Skipping hog flow invocation - workflow is no longer active', {
                        id: item.functionId,
                        status: hogFlow.status,
                    })

                    skippedInvocations.push(item)

                    return
                }

                const hogFlowInvocationState = item.state as CyclotronJobInvocationHogFlow['state']

                // Warehouse-row invocations don't have a real person — the row is the unit of work
                // and person-dependent steps no-op for these flows. Explicitly skip the person lookup
                // rather than relying on event.distinct_id being empty so future changes to the
                // synthetic event shape don't accidentally re-enable the lookup.
                const isWarehouseRow = hogFlow.trigger?.type === 'data-warehouse-table'
                const personIdOrDistinctId = isWarehouseRow
                    ? undefined
                    : hogFlowInvocationState.event.distinct_id || hogFlowInvocationState.personId
                const kind = hogFlowInvocationState.event.distinct_id ? 'distinct_id' : 'person_id'

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

                loadedInvocations.push({
                    ...item,
                    state: hogFlowInvocationState,
                    hogFlow,
                    person: person ?? undefined,
                    groups,
                    filterGlobals,
                })
            })
        )

        await this.cyclotronJobQueue.dequeueInvocations(failedInvocations)
        await this.cyclotronJobQueue.cancelInvocations(skippedInvocations)

        return loadedInvocations
    }
}
