import { getEmbedSnippet, getSurveyUrl } from './CopySurveyLink'

describe('getSurveyUrl', () => {
    const originalLocation = window.location

    afterEach(() => {
        Object.defineProperty(window, 'location', { value: originalLocation, configurable: true })
    })

    test.each([
        ['https://us.posthog.com', 'https://posthogsurveys.com/survey-id'],
        ['https://eu.posthog.com', 'https://eu.posthogsurveys.com/survey-id'],
        ['https://posthog.example.com', 'https://posthog.example.com/external_surveys/survey-id'],
    ])('on %s links to %s', (appOrigin, expectedUrl) => {
        Object.defineProperty(window, 'location', { value: new URL(appOrigin), configurable: true })

        expect(getSurveyUrl('survey-id')).toBe(expectedUrl)
    })
})

describe('getEmbedSnippet', () => {
    it('accepts height messages from the sandboxed survey iframe', () => {
        const snippet = getEmbedSnippet('survey-id')

        expect(snippet).toContain('if (e.source !== iframe.contentWindow) return;')
        expect(snippet).toContain("if (e.origin !== 'null' && e.origin !== 'http://localhost') return;")
        expect(snippet).toContain("e.data.type === 'posthog:survey:height' && e.data.surveyId === 'survey-id'")
    })
})
