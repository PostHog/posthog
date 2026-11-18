import { get } from 'lodash'

import { HogFlowAction } from '../schema/hogflow'
import { capWorkflowStepResult } from './workflow-step-result'

describe('workflow step result byte budget', () => {
    const dispatch = { id: 'task-1', run_id: 'run-1', status: 'completed' }

    it.each([
        { final_message: '😀'.repeat(1500) },
        { final_message: '漢'.repeat(1500), summary: '字'.repeat(1500) },
        { final_message: '\\"\n'.repeat(1500), nested: { summary: '😀'.repeat(1500) } },
        { pr_urls: Array.from({ length: 1000 }, (_, index) => `https://example.com/pr/${index}`) },
    ])('fits Unicode, escaped text, nested values, and URL lists: %j', (payload) => {
        const variables = { existing: 'x'.repeat(3500) }
        const result = capWorkflowStepResult(dispatch, payload, variables, { key: 'result' })

        expect(Buffer.byteLength(JSON.stringify({ ...variables, result }))).toBeLessThanOrEqual(5120)
        expect(result).toMatchObject(dispatch)
        for (const url of (result.pr_urls ?? []) as string[]) {
            expect(payload.pr_urls).toContain(url)
        }
    })

    it.each<HogFlowAction['output_variable']>([
        { key: 'result' },
        { key: 'result', spread: true },
        { key: 'result', result_path: 'nested', spread: true },
        [{ key: 'first' }, { key: 'second' }],
        { key: 'result', result_path: 'final_message' },
    ])('accounts for the selected output mapping: %j', (outputVariable) => {
        const variables: Record<string, unknown> = { existing: 'x'.repeat(4000), result: 'old output'.repeat(80) }
        const payload = { final_message: '😀'.repeat(1500), nested: { summary: '漢'.repeat(1500) } }
        const result = capWorkflowStepResult(dispatch, payload, variables, outputVariable)
        const stored = { ...variables }
        for (const output of Array.isArray(outputVariable) ? outputVariable : [outputVariable!]) {
            const resolved = output.result_path ? get(result, output.result_path) : result
            if (output.spread && resolved && typeof resolved === 'object' && !Array.isArray(resolved)) {
                Object.assign(
                    stored,
                    Object.fromEntries(Object.entries(resolved).map(([key, value]) => [`${output.key}_${key}`, value]))
                )
            } else {
                stored[output.key] = resolved
            }
        }
        expect(Buffer.byteLength(JSON.stringify(stored))).toBeLessThanOrEqual(5120)
        expect(variables.result).toBe('old output'.repeat(80))
    })

    it('reports when even the fixed run identifiers cannot fit', () => {
        expect(() => capWorkflowStepResult(dispatch, {}, { existing: 'x'.repeat(5100) }, { key: 'result' })).toThrow(
            'Workflow variables exceed the 5KB limit'
        )
    })
})
