import { validatePromptConfig } from './utils'

describe('validatePromptConfig', () => {
    // Guards the JSON-object contract with the API: arrays/scalars are rejected server-side,
    // and an empty editor must not block publishing.
    test.each([
        ['empty string', '', undefined],
        ['whitespace only', '   ', undefined],
        ['valid object', '{"model": "gpt-5", "temperature": 0.2}', undefined],
        ['array', '[1, 2]', 'Config must be a JSON object, e.g. {"model": "gpt-5", "temperature": 0.2}'],
        ['scalar', '42', 'Config must be a JSON object, e.g. {"model": "gpt-5", "temperature": 0.2}'],
        ['null literal', 'null', 'Config must be a JSON object, e.g. {"model": "gpt-5", "temperature": 0.2}'],
        ['invalid JSON', '{model: gpt-5}', 'Config must be valid JSON'],
    ])('%s', (_label, config, expected) => {
        expect(validatePromptConfig(config)).toBe(expected)
    })
})
