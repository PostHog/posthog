import { PipelineResultType } from '~/ingestion/framework/results'
import { PluginEvent } from '~/plugin-scaffold'
import { createTestPluginEvent } from '~/tests/helpers/plugin-event'

import { createStripPersonUpdatePropertiesStep } from './strip-person-update-properties-step'

describe('stripPersonUpdatePropertiesStep', () => {
    const step = createStripPersonUpdatePropertiesStep()

    const inputWithProperties = (properties: PluginEvent['properties']) => ({
        normalizedEvent: createTestPluginEvent({ properties }),
    })

    it('strips both $set and $set_once while keeping other properties', async () => {
        const input = inputWithProperties({
            $set: { email: 'user@example.com' },
            $set_once: { initial_referrer: 'google' },
            $current_url: 'http://example.com',
            foo: 'bar',
        })

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.normalizedEvent.properties).toEqual({
                $current_url: 'http://example.com',
                foo: 'bar',
            })
        }
    })

    it.each(['$set', '$set_once'])('strips %s when it is the only update property present', async (key) => {
        const input = inputWithProperties({ [key]: { email: 'user@example.com' }, kept: 'value' })

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.normalizedEvent.properties).not.toHaveProperty(key)
            expect(result.value.normalizedEvent.properties).toEqual({ kept: 'value' })
        }
    })

    it('leaves properties untouched when neither $set nor $set_once is present', async () => {
        const input = inputWithProperties({ $current_url: 'http://example.com', foo: 'bar' })

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.normalizedEvent.properties).toEqual({
                $current_url: 'http://example.com',
                foo: 'bar',
            })
        }
    })

    it('handles an event with no properties without throwing', async () => {
        const input = { normalizedEvent: createTestPluginEvent({ properties: undefined }) }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.normalizedEvent.properties).toBeUndefined()
        }
    })

    it('mutates the event in place and passes through other input fields', async () => {
        const stepWithExtra = createStripPersonUpdatePropertiesStep<{ normalizedEvent: PluginEvent; extra: string }>()
        const normalizedEvent = createTestPluginEvent({
            properties: { $set: { email: 'user@example.com' }, foo: 'bar' },
        })
        const input = { normalizedEvent, extra: 'preserved' }

        const result = await stepWithExtra(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value).toBe(input)
            expect(result.value.normalizedEvent).toBe(normalizedEvent)
            expect(result.value.normalizedEvent.properties).toEqual({ foo: 'bar' })
            expect(result.value.extra).toBe('preserved')
        }
    })
})
