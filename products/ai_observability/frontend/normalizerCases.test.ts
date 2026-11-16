import { RecipeNormalizer } from '@posthog/llm-normalizer'

import normalizerCases from '../shared/normalizer_cases.json'

// Whole-engine cases live in a shared data file so another implementation of the engine can run the same cases,
// so add or change them there rather than inline. The file is imported rather than read, which lets Jest's
// related-test selection run this test when only the cases change.
interface NormalizerCase {
    name: string
    call: string
    input: unknown
    default_role: string
    tools?: unknown
    expected: { messages: unknown[]; recognized: boolean }
}

const cases: NormalizerCase[] = normalizerCases.cases

describe('normalizer cases', () => {
    const normalizer = new RecipeNormalizer()

    it('holds uniquely named cases', () => {
        expect(cases.length).toBeGreaterThan(0)
        expect(new Set(cases.map((c) => c.name)).size).toBe(cases.length)
    })

    it.each(cases.map((c) => [c.name, c] as const))('%s', (_, c) => {
        const outcome =
            c.call === 'normalizeMessage'
                ? normalizer.normalizeMessage(c.input, c.default_role)
                : normalizer.normalizeMessages(c.input, c.default_role, c.tools)
        expect(outcome).toEqual(c.expected)
    })

    describe('inputs JSON cannot encode', () => {
        it('returns no messages for undefined input', () => {
            expect(normalizer.normalizeMessages(undefined, 'assistant')).toEqual({ messages: [], recognized: true })
        })

        it('handles Vercel AI SDK tool-result with non-serializable output', () => {
            const circular: Record<string, unknown> = { key: 'value' }
            circular.self = circular
            const message = { type: 'tool-result', toolCallId: 'tc_circ', toolName: 'bad_tool', output: circular }
            expect(normalizer.normalizeMessage(message, 'assistant').messages).toEqual([
                { role: 'assistant (tool result)', content: '[object Object]', tool_call_id: 'tc_circ' },
            ])
        })
    })
})
