import {
    evaluationOffersSessionTarget,
    evaluationSupportsReports,
    evaluationSupportsRunOutcomes,
} from './evaluationCapabilities'
import type { EvaluationOutputType, EvaluationTarget } from './types'

describe('evaluationCapabilities', () => {
    it.each<
        [
            outputType: EvaluationOutputType,
            target: EvaluationTarget,
            supportsReports: boolean,
            supportsRunOutcomes: boolean,
        ]
    >([
        ['boolean', 'generation', true, true],
        ['sentiment', 'generation', true, false],
        // Sentiment is generation-only, so the aggregate targets report on boolean alone.
        // This pins the frontend twin of REPORTABLE_OUTPUT_TYPES_BY_TARGET.
        ['boolean', 'trace', true, false],
        ['sentiment', 'trace', false, false],
        ['boolean', 'session', true, false],
        ['sentiment', 'session', false, false],
    ])(
        'supports the expected capabilities for %s %s evaluations',
        (outputType, target, supportsReports, supportsRunOutcomes) => {
            const evaluation = { output_type: outputType, target }

            expect(evaluationSupportsReports(evaluation)).toBe(supportsReports)
            expect(evaluationSupportsRunOutcomes(evaluation)).toBe(supportsRunOutcomes)
        }
    )

    // An evaluation already targeting a session must keep the option listed even with the flag off,
    // since the API and MCP can create one. Otherwise the picker renders the raw 'session' value.
    it.each<[target: EvaluationTarget | null, settlingStrategyEnabled: boolean, offered: boolean]>([
        ['generation', true, true],
        ['generation', false, false],
        ['trace', false, false],
        ['session', false, true],
        ['session', true, true],
        [null, false, false],
    ])('offers the session target for a %s evaluation when the flag is %s', (target, flagEnabled, offered) => {
        const evaluation = target === null ? null : { target }

        expect(evaluationOffersSessionTarget(evaluation, flagEnabled)).toBe(offered)
    })
})
