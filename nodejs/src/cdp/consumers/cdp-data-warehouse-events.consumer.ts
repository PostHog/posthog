import { Message } from 'node-rdkafka'

import { instrumented } from '~/common/tracing/tracing-utils'

import { convertDataWarehouseEventToHogFunctionInvocationGlobals } from '../../cdp/utils'
import { PluginsServerConfig } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { CdpDataWarehouseEventSchema } from '../schema'
import { HogFunctionInvocationGlobals, HogFunctionType, HogFunctionTypeType } from '../types'
import { CdpConsumerBaseDeps } from './cdp-base.consumer'
import { CdpEventsConsumer } from './cdp-events.consumer'
import { counterParseError } from './metrics'

/* NOTE: This is not released yet - outstanding work to be done:
   * Make it clear that Workflows are not supported / add support (the filter hog function logic is the key part)
   * It writes to a dedicated topic but its unclear if we actually want to separate the workload from
     the normal hog topic
*/
export class CdpDatawarehouseEventsConsumer extends CdpEventsConsumer {
    protected name = 'CdpDatawarehouseEventsConsumer'
    protected hogTypes: HogFunctionTypeType[] = ['destination']

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps) {
        super(
            config,
            deps,
            'cdp_data_warehouse_source_table',
            'cdp-data-warehouse-events-consumer',
            'datawarehouse_table'
        )
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
