import { PluginEvent } from '~/plugin-scaffold'

import { numericProperty } from './cost-utils'
import { createAIEvent } from './test-helpers'

describe('numericProperty()', () => {
    it.each<{ description: string; value: unknown; expected: number }>([
        { description: 'returns the value when it is a finite number', value: 100, expected: 100 },
        { description: 'preserves negative numbers', value: -50, expected: -50 },
        { description: 'returns 0 for NaN', value: Number.NaN, expected: 0 },
        { description: 'returns 0 for Infinity', value: Number.POSITIVE_INFINITY, expected: 0 },
        { description: 'parses numeric strings', value: '100', expected: 100 },
        { description: 'parses negative numeric strings', value: '-25', expected: -25 },
        { description: 'parses decimal numeric strings', value: '12.5', expected: 12.5 },
        { description: 'returns 0 for non-numeric strings', value: 'not-a-number', expected: 0 },
        { description: 'returns 0 for empty strings', value: '', expected: 0 },
        { description: 'returns 0 for null', value: null, expected: 0 },
        { description: 'returns 0 for undefined', value: undefined, expected: 0 },
        { description: 'returns 0 for objects', value: { foo: 'bar' }, expected: 0 },
        { description: 'returns 0 for booleans', value: true, expected: 0 },
    ])('$description', ({ value, expected }) => {
        const event = createAIEvent({ $ai_audio_input_tokens: value })
        expect(numericProperty(event, '$ai_audio_input_tokens')).toBe(expected)
    })

    it('returns 0 when the event has no properties', () => {
        const event = { ...createAIEvent(), properties: undefined } as PluginEvent
        expect(numericProperty(event, '$ai_audio_input_tokens')).toBe(0)
    })

    it('returns 0 when the property is absent', () => {
        const event = createAIEvent({ other_prop: 100 })
        expect(numericProperty(event, '$ai_audio_input_tokens')).toBe(0)
    })
})
