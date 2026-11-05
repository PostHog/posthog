import { hogAdaptPrompt, hogSnippetsFor, judgePromptsFor } from './evaluationSnippets'
import type { EvaluationConfig } from './types'

const evaluation = (overrides: Partial<EvaluationConfig>): EvaluationConfig =>
    ({
        evaluation_type: 'hog',
        evaluation_config: { source: '' },
        output_type: 'boolean',
        output_config: {},
        target: 'generation',
        ...overrides,
    }) as EvaluationConfig

describe('evaluationSnippets', () => {
    it.each([
        ['a trace template only for traces', evaluation({ target: 'trace' }), 'Repeated tool calls', true],
        ['no trace template for generations', evaluation({ target: 'generation' }), 'Repeated tool calls', false],
        ['score templates only for scores', evaluation({ output_type: 'boolean' }), 'Cost per run', false],
        ['score templates for scores', evaluation({ output_type: 'numeric' }), 'Cost per run', true],
    ])('hog code: offers %s', (_name, config, label, offered) => {
        expect(hogSnippetsFor(config).templates.some((snippet) => snippet.label === label)).toBe(offered)
    })

    it.each([
        ['a generation prompt for generations', evaluation({ target: 'generation' }), 'Helpfulness', true],
        [
            'no trace prompt for generations',
            evaluation({ target: 'generation' }),
            'Claimed success without evidence',
            false,
        ],
        ['a trace prompt for traces', evaluation({ target: 'trace' }), 'Claimed success without evidence', true],
    ])('judge prompts: offers %s', (_name, config, label, offered) => {
        expect(judgePromptsFor(config).some((template) => template.label === label)).toBe(offered)
    })

    it('offers no template code or prompt for categories, which name their own keys', () => {
        const config = evaluation({
            output_type: 'categorical',
            output_config: { options: [{ key: 'resolved', label: 'Resolved' }] },
        })
        expect(hogSnippetsFor(config)).toEqual({
            starters: [{ label: 'Resolved', source: "return ['resolved'];" }],
            templates: [],
        })
        expect(judgePromptsFor(config)).toEqual([])
    })

    it('tells PostHog AI the code, the level, and the keys it must return', () => {
        const prompt = hogAdaptPrompt(
            evaluation({
                output_type: 'categorical',
                target: 'trace',
                output_config: { options: [{ key: 'resolved', label: 'Resolved' }], allows_na: true },
            }),
            "return ['resolved'];"
        )
        expect(prompt).toContain('runs on each trace and must return a list of category keys from resolved')
        expect(prompt).toContain('or null when it does not apply')
        expect(prompt).toContain("return ['resolved'];")
    })
})
