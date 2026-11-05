import { hogSnippetsFor } from './hogSnippets'
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

describe('hogSnippetsFor', () => {
    it.each([
        ['a trace template only for traces', evaluation({ target: 'trace' }), 'Repeated tool calls', true],
        ['no trace template for generations', evaluation({ target: 'generation' }), 'Repeated tool calls', false],
        ['score templates only for scores', evaluation({ output_type: 'boolean' }), 'Cost per run', false],
        ['score templates for scores', evaluation({ output_type: 'numeric' }), 'Cost per run', true],
    ])('offers %s', (_name, config, label, offered) => {
        expect(hogSnippetsFor(config).templates.some((snippet) => snippet.label === label)).toBe(offered)
    })

    it('offers no template code for categories, which return their own keys', () => {
        const config = evaluation({
            output_type: 'categorical',
            output_config: { options: [{ key: 'resolved', label: 'Resolved' }] },
        })
        expect(hogSnippetsFor(config)).toEqual({
            starters: [{ label: 'Resolved', source: "return ['resolved'];" }],
            templates: [],
        })
    })
})
