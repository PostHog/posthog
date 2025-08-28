import { instrumented } from '~/common/tracing/tracing-utils'

import { Hub } from '../../types'
import { logger } from '../../utils/logger'
import {
    CyclotronJobInvocation,
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationResult,
    CyclotronPerson,
} from '../types'
import { getPersonDisplayName } from '../utils'
import { convertToHogFunctionFilterGlobal } from '../utils/hog-function-filtering'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

export class CdpCyclotronWorkerHogFlow extends CdpCyclotronWorker {
    protected name = 'CdpCyclotronWorkerHogFlow'

    constructor(hub: Hub) {
        super(hub, 'hogflow')
    }

    @instrumented('cdpConsumer.handleEachBatch.executeInvocations')
    public async processInvocations(invocations: CyclotronJobInvocation[]): Promise<CyclotronJobInvocationResult[]> {
        this.personsManager.clear() // We want to load persons fresh each time
        const loadedInvocations = await this.loadHogFlows(invocations)
        return await Promise.all(loadedInvocations.map((item) => this.hogFlowExecutor.execute(item)))
    }

    @instrumented('cdpConsumer.handleEachBatch.loadHogFlows')
    protected async loadHogFlows(invocations: CyclotronJobInvocation[]): Promise<CyclotronJobInvocationHogFlow[]> {
        const loadedInvocations: CyclotronJobInvocationHogFlow[] = []
        const failedInvocations: CyclotronJobInvocation[] = []

        await Promise.all(
            invocations.map(async (item) => {
                const team = await this.hub.teamManager.getTeam(item.teamId)
                const hogFlow = await this.hogFlowManager.getHogFlow(item.functionId)
                if (!hogFlow || !team) {
                    logger.error('⚠️', 'Error finding hog flow', {
                        id: item.functionId,
                    })

                    failedInvocations.push(item)

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

                const person: CyclotronPerson | undefined = dbPerson
                    ? {
                          id: dbPerson.id,
                          properties: dbPerson.properties,
                          name: personDisplayName,
                          url: `${this.hub.SITE_URL}/project/${hogFlow.team_id}/persons/${encodeURIComponent(
                              hogFlowInvocationState.event.distinct_id
                          )}`,
                      }
                    : undefined

                const filterGlobals = convertToHogFunctionFilterGlobal({
                    event: hogFlowInvocationState.event,
                    person,
                    // TODO: Load groups as well
                    groups: {},
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

        return loadedInvocations
    }
}
