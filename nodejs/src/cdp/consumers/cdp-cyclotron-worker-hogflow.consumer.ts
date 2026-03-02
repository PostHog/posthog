import { instrumented } from '~/common/tracing/tracing-utils'
import { PluginsServerConfig } from '~/types'

import { logger } from '../../utils/logger'
import {
    CyclotronJobInvocation,
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationResult,
    CyclotronPerson,
} from '../types'
import { getPersonDisplayName } from '../utils'
import { convertToHogFunctionFilterGlobal } from '../utils/hog-function-filtering'
import { CdpConsumerBaseDeps } from './cdp-base.consumer'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

export class CdpCyclotronWorkerHogFlow extends CdpCyclotronWorker {
    protected name = 'CdpCyclotronWorkerHogFlow'

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps) {
        super(config, deps, 'hogflow')
    }

    @instrumented('cdpConsumer.handleEachBatch.executeInvocations')
    public async processInvocations(invocations: CyclotronJobInvocation[]): Promise<CyclotronJobInvocationResult[]> {
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

                    return null
                }

                // Skip execution if the workflow is no longer active (e.g., disabled/archived)
                if (hogFlow.status !== 'active') {
                    logger.info('⏭️', 'Skipping hog flow invocation - workflow is no longer active', {
                        id: item.functionId,
                        status: hogFlow.status,
                    })

                    skippedInvocations.push(item)

                    return null
                }

                const hogFlowInvocationState = item.state as CyclotronJobInvocationHogFlow['state']

                const dbPerson = await this.personsManager.get({
                    teamId: hogFlow.team_id,
                    distinctId: hogFlowInvocationState.event.distinct_id,
                })

                const personDisplayName = getPersonDisplayName(
                    team,
                    hogFlowInvocationState.event.distinct_id,
                    dbPerson?.properties ?? {}
                )

                if (!dbPerson && hogFlow.trigger?.type === 'event') {
                    logger.warn('⚠️', 'Person not found for hog flow invocation', {
                        hogFlowId: hogFlow.id,
                        distinctId: hogFlowInvocationState.event.distinct_id,
                        invocationId: item.id,
                    })
                }

                const person: CyclotronPerson | undefined = dbPerson
                    ? {
                          id: dbPerson.id,
                          properties: dbPerson.properties,
                          name: personDisplayName,
                          url: `${this.config.SITE_URL}/project/${hogFlow.team_id}/person/${encodeURIComponent(
                              hogFlowInvocationState.event.distinct_id
                          )}`,
                      }
                    : undefined

                const filterGlobals = convertToHogFunctionFilterGlobal({
                    event: hogFlowInvocationState.event,
                    person,
                    // TODO: Load groups as well
                    groups: {},
                    variables: hogFlowInvocationState.variables || {},
                })

                loadedInvocations.push({
                    ...item,
                    state: hogFlowInvocationState,
                    hogFlow,
                    person,
                    filterGlobals,
                })
            })
        )

        await this.cyclotronJobQueue.dequeueInvocations(failedInvocations)
        await this.cyclotronJobQueue.cancelInvocations(skippedInvocations)

        return loadedInvocations
    }
}
