import { PluginEvent } from '~/plugin-scaffold'

import { drop, ok } from '../../../pipelines/results'
import { ProcessingStep } from '../../../pipelines/steps'
import { AI_GATEWAY_HOSTS, gatewayHostForClientEvent } from '../../gateway-dedup'
import { aiGatewayDedupDroppedCounter } from '../../metrics'

type DropGatewayRoutedEventsInput = {
    normalizedEvent: PluginEvent
}

/**
 * Drops client `$ai_generation` events routed through the AI gateway — the gateway
 * emits its own canonical event, so the client copy would double-count.
 *
 * Must run after `createProcessAiEventStep`, which maps OTel `server.address` to
 * `$ai_base_url` — the point where it holds the gateway host for both SDK and OTel events.
 */
export function createDropGatewayRoutedEventsStep<TInput extends DropGatewayRoutedEventsInput>(
    gatewayHosts: ReadonlySet<string> = AI_GATEWAY_HOSTS
): ProcessingStep<TInput, TInput> {
    return function dropGatewayRoutedEventsStep(input) {
        const host = gatewayHostForClientEvent(input.normalizedEvent, gatewayHosts)
        if (host !== null) {
            aiGatewayDedupDroppedCounter.labels({ host }).inc()
            return Promise.resolve(drop('gateway_routed_duplicate'))
        }
        return Promise.resolve(ok(input))
    }
}
