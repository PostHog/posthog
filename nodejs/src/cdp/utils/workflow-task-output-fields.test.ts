import { buildWorkflowTaskOutputFields } from './workflow-task-output-fields'

describe('buildWorkflowTaskOutputFields', () => {
    const variables = [
        { key: 'verdict', type: 'string' as const, label: 'Verdict', description: 'ship or hold' },
        { key: 'score', type: 'number' as const, label: 'Confidence score' },
        { key: 'urgent', type: 'boolean' as const, label: 'urgent' },
        { key: 'details', type: 'json' as const, label: 'details' },
    ]

    it('turns each output.<name> mapping into a typed field', () => {
        const fields = buildWorkflowTaskOutputFields(
            [
                { key: 'verdict', result_path: 'output.verdict' },
                { key: 'score', result_path: 'output.score' },
                { key: 'urgent', result_path: 'output.is_urgent' },
                { key: 'details', result_path: 'output.details' },
            ],
            variables
        )

        expect(fields).toEqual({ verdict: 'string', score: 'number', is_urgent: 'boolean', details: 'string' })
    })

    it.each([
        ['a mapping of the whole result', { key: 'task' }],
        ['a mapping of a fixed field', { key: 'run', result_path: 'run_id' }],
        ['a spread of the output object', { key: 'task', result_path: 'output', spread: true }],
        ['a nested output path', { key: 'verdict', result_path: 'output.a.b' }],
        ['a mapping with no variable selected', { key: '', result_path: 'output.verdict' }],
    ])('asks for nothing when the only mapping is %s', (_name, mapping) => {
        expect(buildWorkflowTaskOutputFields(mapping, variables)).toBeNull()
    })

    it('asks for text when it cannot match the mapping to a variable', () => {
        expect(buildWorkflowTaskOutputFields({ key: 'missing', result_path: 'output.verdict' }, [])).toEqual({
            verdict: 'string',
        })
    })
})
