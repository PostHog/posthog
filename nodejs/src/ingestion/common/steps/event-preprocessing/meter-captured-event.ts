import { Message } from 'node-rdkafka'

import { FinopsUsageMeter } from '~/common/services/finops-usage-meter'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PluginEvent } from '~/plugin-scaffold'
import { Team } from '~/types'

export interface MeterCapturedEventInput {
    message: Message
    team: Team
    event: PluginEvent
}

export function createMeterCapturedEventStep<T extends MeterCapturedEventInput>(
    meter?: FinopsUsageMeter
): ProcessingStep<T, T> {
    return function meterCapturedEvent(input) {
        meter?.queueCapturedEvent({
            eventName: input.event.event,
            teamId: input.team.id,
            orgId: input.team.organization_id,
            byteLength: input.message.size ?? input.message.value?.byteLength ?? 0,
            resourceId: input.message.topic,
        })
        return Promise.resolve(ok(input))
    }
}
