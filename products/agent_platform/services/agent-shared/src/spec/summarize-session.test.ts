import { buildSummaryUserPrompt, parseSummaryResponse, SUMMARY_SYSTEM_PROMPT } from './summarize-session'

describe('buildSummaryUserPrompt', () => {
    it('embeds the digest', () => {
        expect(buildSummaryUserPrompt('user asked X; agent did Y')).toContain('user asked X; agent did Y')
    })
})

describe('parseSummaryResponse', () => {
    it('parses a clean minified JSON object', () => {
        const out = parseSummaryResponse(
            '{"summary":"User asked to deploy; agent deployed.","topic":"deploy help","outcome":"resolved"}'
        )
        expect(out).toEqual({
            summary: 'User asked to deploy; agent deployed.',
            topic: 'deploy help',
            outcome: 'resolved',
        })
    })

    it('tolerates code fences + surrounding prose', () => {
        const raw =
            'Here you go:\n```json\n{"summary":"Asked about pricing.","topic":"pricing","outcome":"abandoned"}\n```'
        expect(parseSummaryResponse(raw)).toMatchObject({ topic: 'pricing', outcome: 'abandoned' })
    })

    it('coerces an unknown outcome to "other"', () => {
        expect(parseSummaryResponse('{"summary":"x","topic":"y","outcome":"wat"}')?.outcome).toBe('other')
    })

    it('collapses whitespace and caps long fields', () => {
        const out = parseSummaryResponse(
            `{"summary":"${'a'.repeat(800)}","topic":"  multi   word  ","outcome":"failed"}`
        )
        expect(out!.summary.length).toBe(600)
        expect(out!.topic).toBe('multi word')
    })

    it('returns null when there is no JSON or no summary', () => {
        expect(parseSummaryResponse('the model rambled with no json')).toBeNull()
        expect(parseSummaryResponse('{"topic":"x","outcome":"resolved"}')).toBeNull()
    })

    it('system prompt pins the JSON contract', () => {
        expect(SUMMARY_SYSTEM_PROMPT).toContain('"outcome"')
        expect(SUMMARY_SYSTEM_PROMPT).toMatch(/only.*json/i)
    })
})
