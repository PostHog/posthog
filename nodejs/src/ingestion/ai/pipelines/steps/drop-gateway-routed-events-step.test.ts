import { PluginEvent } from '~/plugin-scaffold'

import { createTestPluginEvent } from '../../../../../tests/helpers/plugin-event'
import { PipelineResultType } from '../../../pipelines/results'
import { createDropGatewayRoutedEventsStep } from './drop-gateway-routed-events-step'

const createEvent = (event: string, properties: Record<string, unknown>) => createTestPluginEvent({ event, properties })

describe('dropGatewayRoutedEventsStep', () => {
    it('drops a client $ai_generation routed through the gateway', async () => {
        const step = createDropGatewayRoutedEventsStep()
        const input = {
            normalizedEvent: createEvent('$ai_generation', { $ai_base_url: 'https://ai-gateway.us.posthog.com/v1' }),
        }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.DROP)
        if (result.type === PipelineResultType.DROP) {
            expect(result.reason).toBe('gateway_routed_duplicate')
        }
    })

    it.each([
        ["the gateway's own event", '$ai_generation', { $ai_base_url: 'https://api.anthropic.com', $ai_gateway: true }],
        ['a direct provider call', '$ai_generation', { $ai_base_url: 'https://api.openai.com' }],
        ['a non-generation event', '$ai_span', { $ai_base_url: 'https://ai-gateway.us.posthog.com' }],
    ])('passes through %s', async (_label, eventName, properties) => {
        const step = createDropGatewayRoutedEventsStep()
        const input = { normalizedEvent: createEvent(eventName, properties) }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value).toBe(input)
        }
    })

    it('preserves additional input fields when passing through', async () => {
        const step = createDropGatewayRoutedEventsStep<{ normalizedEvent: PluginEvent; extraField: string }>()
        const input = {
            normalizedEvent: createEvent('$ai_generation', { $ai_base_url: 'https://api.openai.com' }),
            extraField: 'preserved',
        }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.extraField).toBe('preserved')
        }
    })
})
