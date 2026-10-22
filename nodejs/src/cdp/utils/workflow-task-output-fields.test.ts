import { buildWorkflowTaskOutputRequest } from './workflow-task-output-fields'

describe('buildWorkflowTaskOutputRequest', () => {
    const variables = [
        { key: 'verdict', type: 'string' as const, label: 'Verdict' },
        { key: 'score', type: 'number' as const, label: 'Confidence score' },
        { key: 'urgent', type: 'boolean' as const, label: 'urgent' },
        { key: 'details', type: 'json' as const, label: 'details' },
    ]

    it('turns each output.<name> mapping into a typed field with its instruction', () => {
        const request = buildWorkflowTaskOutputRequest(
            [
                { key: 'verdict', result_path: 'output.verdict', description: ' ship or hold ' },
                { key: 'score', result_path: 'output.score', description: '   ' },
                { key: 'urgent', result_path: 'output.is_urgent' },
                { key: 'details', result_path: 'output.details', description: null },
            ],
            variables
        )

        expect(request).toEqual({
            output_fields: { verdict: 'string', score: 'number', is_urgent: 'boolean', details: 'string' },
            output_field_descriptions: { verdict: 'ship or hold' },
        })
    })

    it.each([
        ['a mapping of the whole result', { key: 'task' }],
        ['a mapping of a fixed field', { key: 'run', result_path: 'run_id' }],
        ['a spread of the output object', { key: 'task', result_path: 'output', spread: true }],
        ['a nested output path', { key: 'verdict', result_path: 'output.a.b' }],
        ['a mapping with no variable selected', { key: '', result_path: 'output.verdict' }],
    ])('asks for nothing when the only mapping is %s', (_name, mapping) => {
        expect(buildWorkflowTaskOutputRequest(mapping, variables)).toBeNull()
    })

    it('asks for text when it cannot match the mapping to a variable', () => {
        expect(buildWorkflowTaskOutputRequest({ key: 'missing', result_path: 'output.verdict' }, [])).toEqual({
            output_fields: { verdict: 'string' },
        })
    })
})
