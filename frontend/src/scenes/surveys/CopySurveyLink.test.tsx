import { getEmbedSnippet } from './CopySurveyLink'

describe('getEmbedSnippet', () => {
    it('accepts height messages from the sandboxed survey iframe', () => {
        const snippet = getEmbedSnippet('survey-id')

        expect(snippet).toContain('if (e.source !== iframe.contentWindow) return;')
        expect(snippet).toContain("if (e.origin !== 'null' && e.origin !== 'http://localhost') return;")
        expect(snippet).toContain("e.data.type === 'posthog:survey:height' && e.data.surveyId === 'survey-id'")
    })
})
