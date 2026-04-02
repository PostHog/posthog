import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { instrumented } from '~/common/tracing/tracing-utils'

import { PluginsServerConfig, Team } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { CdpDataWarehouseEvent, CdpDataWarehouseEventSchema } from '../schema'
import { HogFunctionInvocationGlobals, HogFunctionType, HogFunctionTypeType } from '../types'
import { CdpConsumerBaseDeps } from './cdp-base.consumer'
import { CdpEventsConsumer } from './cdp-events.consumer'
import { counterParseError } from './metrics'

/* NOTE: This is not released yet - outstanding work to be done:
 * Make it clear that Workflows are not supported / add support (the filter hog function logic is the key part)
 */
export class CdpDatawarehouseEventsConsumer extends CdpEventsConsumer {
    protected name = 'CdpDatawarehouseEventsConsumer'
    protected hogTypes: HogFunctionTypeType[] = ['destination']

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps) {
        super(config, deps, 'cdp_data_warehouse_source_table', 'cdp-data-warehouse-events-consumer')
    }

    protected filterHogFunction(hogFunction: HogFunctionType): boolean {
        return (hogFunction.filters?.source ?? 'events') === 'data-warehouse-table'
    }

    @instrumented('cdpConsumer.handleEachBatch.parseKafkaMessages')
    public async _parseKafkaBatch(messages: Message[]): Promise<HogFunctionInvocationGlobals[]> {
        return await this.runWithHeartbeat(async () => {
            const events: HogFunctionInvocationGlobals[] = []

            await Promise.all(
                messages.map(async (message) => {
                    try {
                        const kafkaEvent = parseJSON(message.value!.toString()) as unknown
                        const event = CdpDataWarehouseEventSchema.parse(kafkaEvent)

                        const [teamHogFunctions, teamHogFlows, team] = await Promise.all([
                            this.hogFunctionManager.getHogFunctionsForTeam(event.team_id, this.hogTypes),
                            this.hogFlowManager.getHogFlowsForTeam(event.team_id),
                            this.deps.teamManager.getTeam(event.team_id),
                        ])

                        if ((!teamHogFunctions.length && !teamHogFlows.length) || !team) {
                            return
                        }

                        events.push(
                            convertDataWarehouseEventToHogFunctionInvocationGlobals(event, team, this.config.SITE_URL)
                        )
                    } catch (e) {
                        logger.error('Error parsing message', e)
                        counterParseError.labels({ error: e.message }).inc()
                    }
                })
            )

            return events
        })
    }
}

function convertDataWarehouseEventToHogFunctionInvocationGlobals(
    event: CdpDataWarehouseEvent,
    team: Team,
    siteUrl: string
): HogFunctionInvocationGlobals {
    const data = event.properties
    const projectUrl = `${siteUrl}/project/${team.id}`

    const context: HogFunctionInvocationGlobals = {
        project: {
            id: team.id,
            name: team.name,
            url: projectUrl,
        },
        event: {
            uuid: 'data-warehouse-table-uuid-do-not-use',
            event: 'data-warehouse-table-event-do-not-use',
            elements_chain: '', // Not applicable but left here for compatibility
            distinct_id: 'data-warehouse-table-distinct-id-do-not-use',
            properties: data,
            timestamp: DateTime.now().toISO(),
            url: '',
        },
    }

    return context
}
