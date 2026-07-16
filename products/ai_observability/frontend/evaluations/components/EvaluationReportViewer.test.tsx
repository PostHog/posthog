import { cleanup, render, screen } from '@testing-library/react'

import type { EvaluationReportRun, EvaluationReportStoredMetrics } from '../types'
import { EvaluationReportViewer, summarizeEvaluationReportResults } from './EvaluationReportViewer'

function buildMetrics(fields: EvaluationReportStoredMetrics): EvaluationReportStoredMetrics {
    return {
        total_runs: 10,
        period_start: '2026-07-01T00:00:00Z',
        period_end: '2026-07-02T00:00:00Z',
        previous_total_runs: null,
        previous_result_counts: null,
        previous_result_rates: null,
        ...fields,
    }
}

function buildReportRun(metrics: EvaluationReportStoredMetrics): EvaluationReportRun {
    return {
        id: 'run-id',
        report: 'report-id',
        content: { title: 'Evaluation report', sections: [], citations: [], metrics },
        metadata: null,
        period_start: '2026-07-01T00:00:00Z',
        period_end: '2026-07-02T00:00:00Z',
        delivery_status: 'delivered',
        delivery_errors: [],
        created_at: '2026-07-02T00:00:00Z',
    }
}

describe('EvaluationReportViewer', () => {
    afterEach(cleanup)

    it.each<[name: string, fields: EvaluationReportStoredMetrics, expected: string]>([
        [
            'sentiment metrics',
            {
                output_type: 'sentiment',
                result_counts: { positive: 4, neutral: 3, negative: 2 },
                result_rates: { positive: 44.44, neutral: 33.33, negative: 22.22 },
            },
            'Positive 4 (44.4%) · Neutral 3 (33.3%) · Negative 2 (22.2%)',
        ],
        [
            'boolean metrics',
            {
                output_type: 'boolean',
                result_counts: { pass: 7, fail: 2, na: 1 },
                result_rates: { pass: 70, fail: 20, na: 10 },
                pass_rate: 77.78,
            },
            'Pass rate 77.8% · Pass 7 · Fail 2 · N/A 1',
        ],
        ['partial boolean metrics', { pass_rate: 80 }, 'Pass rate 80.0%'],
        [
            'partial sentiment metrics',
            {
                output_type: 'sentiment',
                result_rates: { positive: 60, neutral: 30, negative: 10 },
            },
            'Positive 60.0% · Neutral 30.0% · Negative 10.0%',
        ],
    ])('summarizes %s without inventing missing counts', (_, fields, expected) => {
        expect(summarizeEvaluationReportResults(buildMetrics(fields))).toBe(expected)
    })

    it('shows boolean pass rate once and keeps outcome percentages hidden', () => {
        const metrics = buildMetrics({
            output_type: 'boolean',
            result_counts: { pass: 8, fail: 1, na: 1 },
            result_rates: { pass: 80, fail: 10, na: 10 },
            pass_rate: 88.89,
            previous_pass_rate: 80,
        })

        render(<EvaluationReportViewer reportRun={buildReportRun(metrics)} compact />)

        expect(screen.getByText('Pass rate')).toBeTruthy()
        expect(screen.getByText('88.89%')).toBeTruthy()
        expect(screen.getByText('Pass')).toBeTruthy()
        expect(screen.getByText('8').classList.contains('text-success')).toBe(true)
        expect(screen.getByText('Fail').nextElementSibling?.classList.contains('text-danger')).toBe(true)
        expect(screen.getByText(/8.89pp vs previous/).classList.contains('text-success')).toBe(true)
        expect(screen.queryByText('(80.00%)')).toBeNull()
    })

    it('shows sentiment outcome distribution without boolean pass-rate framing', () => {
        const metrics = buildMetrics({
            output_type: 'sentiment',
            result_counts: { positive: 4, neutral: 3, negative: 3 },
            result_rates: { positive: 40, neutral: 30, negative: 30 },
        })

        render(<EvaluationReportViewer reportRun={buildReportRun(metrics)} compact />)

        expect(screen.queryByText('Pass rate')).toBeNull()
        expect(screen.getByText('Positive')).toBeTruthy()
        expect(screen.getByText('(40.00%)')).toBeTruthy()
        expect(screen.getAllByText('(30.00%)')).toHaveLength(2)
    })

    it('preserves a leading heading when a legacy section has no title', () => {
        const reportRun = buildReportRun(buildMetrics({ pass_rate: 80 }))
        reportRun.content.sections = [{ content: '# Important context\n\nKeep this detail.' }]

        render(<EvaluationReportViewer reportRun={reportRun} compact />)

        const markdown = document.querySelector('[data-testid="react-markdown"]')
        expect(markdown?.textContent).toContain('# Important context')
        expect(markdown?.textContent).toContain('Keep this detail.')
    })
})
