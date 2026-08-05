import { getEvaluationResultDisplay } from './EvaluationResultTag'

describe('getEvaluationResultDisplay', () => {
    it.each([
        [undefined, true, 'True'],
        [undefined, false, 'False'],
        ['zero_one' as const, true, '1'],
        ['zero_one' as const, false, '0'],
    ])('with result_format %p labels result %p as %s', (result_format, result, expectedLabel) => {
        const display = getEvaluationResultDisplay({ status: 'completed', result, result_format })

        expect(display.label).toBe(expectedLabel)
        // Sorting and colors key off the verdict, so the format must not change them.
        expect(display.sortValue).toBe(result ? 1 : 0)
        expect(display.type).toBe(result ? 'success' : 'danger')
    })

    it.each([
        ['N/A', { status: 'completed' as const, result: null, result_format: 'zero_one' as const }],
        ['Skipped', { status: 'completed' as const, result: false, result_format: 'zero_one' as const, skipped: true }],
    ])('keeps the %s label under zero_one', (expectedLabel, run) => {
        expect(getEvaluationResultDisplay(run).label).toBe(expectedLabel)
    })
})
