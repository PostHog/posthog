import { correctedSearch } from './commandKCorrection'

describe('correctedSearch', () => {
    test.each([
        ['фзш', 'api'],
        ['ашдеук', 'filter'],
        ['שפן', 'api'],
        ['вфеф сфефдщп', 'data catalog'],
        ['posthog_personal_api_key', 'posthog personal api key'],
        ['api', null],
        ['фзш api', null],
        ['123', null],
    ])('corrects %s to %s', (text, expected) => {
        expect(correctedSearch(text)).toBe(expected)
    })
})
