import { correctedSearch } from './commandKCorrection'

describe('correctedSearch', () => {
    test.each([
        ['posthog_personal_api_key', 'posthog personal api key'],
        ['api', null],
        ['_', null],
    ])('corrects %s to %s', (text, expected) => {
        expect(correctedSearch(text)).toBe(expected)
    })
})
