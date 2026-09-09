import { buildWorkflowTaskOutputSchema } from './workflow-task-output-schema'

describe('buildWorkflowTaskOutputSchema', () => {
    const variables = [
        { key: 'verdict', type: 'string' as const, label: 'Verdict', description: 'ship or hold' },
        { key: 'score', type: 'number' as const, label: 'Confidence score' },
        { key: 'urgent', type: 'boolean' as const, label: 'urgent' },
        { key: 'details', type: 'json' as const, label: 'details' },
    ]

    it('turns each output.<name> mapping into a required, typed property', () => {
        const schema = buildWorkflowTaskOutputSchema(
            [
                { key: 'verdict', result_path: 'output.verdict' },
                { key: 'score', result_path: 'output.score' },
                { key: 'urgent', result_path: 'output.is_urgent' },
                { key: 'details', result_path: 'output.details' },
            ],
            variables
        )

        expect(schema).toEqual({
            type: 'object',
            properties: {
                verdict: { type: 'string', description: 'ship or hold' },
                score: { type: 'number', description: 'Confidence score' },
                is_urgent: { type: 'boolean' },
                details: {},
            },
            required: ['verdict', 'score', 'is_urgent', 'details'],
        })
    })

    it.each([
        ['a mapping of the whole result', { key: 'task' }],
        ['a mapping of a fixed field', { key: 'run', result_path: 'run_id' }],
        ['a spread of the output object', { key: 'task', result_path: 'output', spread: true }],
        ['a nested output path', { key: 'verdict', result_path: 'output.a.b' }],
        ['a mapping with no variable selected', { key: '', result_path: 'output.verdict' }],
    ])('asks for nothing when the only mapping is %s', (_name, mapping) => {
        expect(buildWorkflowTaskOutputSchema(mapping, variables)).toBeNull()
    })

    it('types a field it cannot match to a variable as anything', () => {
        expect(buildWorkflowTaskOutputSchema({ key: 'missing', result_path: 'output.verdict' }, [])).toEqual({
            type: 'object',
            properties: { verdict: {} },
            required: ['verdict'],
        })
    })
})
