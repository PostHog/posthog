import { PluginEvent } from '~/plugin-scaffold'

import { finiteNumberOrUndefined, numericProperty } from './cost-utils'
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
        { description: 'returns 0 for whitespace-only strings', value: '   ', expected: 0 },
        { description: 'returns 0 for hexadecimal literals', value: '0x10', expected: 0 },
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

describe('finiteNumberOrUndefined()', () => {
    it.each<{ description: string; value: unknown; expected: number | undefined }>([
        { description: 'keeps a legitimate 0 distinct from absent', value: 0, expected: 0 },
        { description: 'keeps a legitimate "0" string distinct from absent', value: '0', expected: 0 },
        { description: 'returns the value when it is a finite number', value: 0.001, expected: 0.001 },
        { description: 'parses numeric strings', value: '0.001', expected: 0.001 },
        { description: 'parses exponent notation', value: '1E-7', expected: 1e-7 },
        { description: 'parses a leading decimal point', value: '.5', expected: 0.5 },
        { description: 'trims surrounding whitespace', value: ' 0.001 ', expected: 0.001 },
        { description: 'rejects whitespace-only strings', value: '   ', expected: undefined },
        { description: 'rejects empty strings', value: '', expected: undefined },
        { description: 'rejects currency-formatted strings', value: '$0.001', expected: undefined },
        // js-big-decimal reads these character by character, so adopting Number()'s
        // reading of them would invent a rate rather than parse one.
        { description: 'rejects hexadecimal literals', value: '0x10', expected: undefined },
        { description: 'rejects binary literals', value: '0b101', expected: undefined },
        { description: 'rejects octal literals', value: '0o17', expected: undefined },
        { description: 'rejects numeric separators', value: '1_000', expected: undefined },
        { description: 'rejects thousands separators', value: '1,000', expected: undefined },
        { description: 'rejects the string "Infinity"', value: 'Infinity', expected: undefined },
        { description: 'rejects NaN', value: Number.NaN, expected: undefined },
        { description: 'rejects Infinity', value: Number.POSITIVE_INFINITY, expected: undefined },
        { description: 'rejects null', value: null, expected: undefined },
        { description: 'rejects undefined', value: undefined, expected: undefined },
        { description: 'rejects objects', value: { value: 0.001 }, expected: undefined },
        { description: 'rejects booleans', value: true, expected: undefined },
    ])('$description', ({ value, expected }) => {
        expect(finiteNumberOrUndefined(value)).toBe(expected)
    })
})
