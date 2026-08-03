import { evaluationSupportsReports, evaluationSupportsRunSummary } from './evaluationCapabilities'
import type { EvaluationOutputType, EvaluationTarget } from './types'

describe('evaluationCapabilities', () => {
    it.each<
        [outputType: EvaluationOutputType, target: EvaluationTarget, supportsReports: boolean, supportsSummary: boolean]
    >([
        ['boolean', 'generation', true, true],
        ['sentiment', 'generation', true, false],
        ['boolean', 'trace', true, false],
        ['sentiment', 'trace', false, false],
    ])(
        'supports the expected capabilities for %s %s evaluations',
        (outputType, target, supportsReports, supportsSummary) => {
            const evaluation = { output_type: outputType, target }

            expect(evaluationSupportsReports(evaluation)).toBe(supportsReports)
            expect(evaluationSupportsRunSummary(evaluation)).toBe(supportsSummary)
        }
    )
})
