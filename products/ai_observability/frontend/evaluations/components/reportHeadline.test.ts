import type { EvaluationReportRun, EvaluationReportStoredMetrics } from '../types'
import { reportHeadline } from './reportHeadline'

function runWith(metrics: Partial<EvaluationReportStoredMetrics>): EvaluationReportRun {
    return {
        id: 'run-1',
        report: 'report-1',
        content: {
            title: 'Report',
            sections: [],
            citations: [],
            metrics: { period_start: '', period_end: '', ...metrics } as EvaluationReportStoredMetrics,
            generation_status: 'completed',
        },
        metadata: null,
        period_start: '2026-11-01T00:00:00Z',
        period_end: '2026-11-02T00:00:00Z',
        delivery_status: 'delivered',
        delivery_errors: [],
        delivery_destinations: [],
        created_at: '2026-11-02T00:00:00Z',
    }
}

describe('reportHeadline', () => {
    test.each<[string, Partial<EvaluationReportStoredMetrics>]>([
        [
            'a boolean report with no results',
            {
                output_type: 'boolean',
                total_runs: 0,
                result_counts: { pass: 0, fail: 0 },
                pass_rate: 0,
                previous_pass_rate: 92,
            },
        ],
        [
            'a boolean report where every result is N/A',
            { output_type: 'boolean', total_runs: 4, result_counts: { pass: 0, fail: 0, na: 4 }, pass_rate: 0 },
        ],
        [
            'a sentiment report with no results',
            {
                output_type: 'sentiment',
                total_runs: 0,
                result_counts: { positive: 0, neutral: 0, negative: 0 },
                result_rates: { positive: 0, neutral: 0, negative: 0 },
                previous_result_rates: { negative: 30 },
            },
        ],
    ])('leads with nothing for %s', (_, metrics) => {
        expect(reportHeadline(runWith(metrics))).toBeNull()
    })
})
