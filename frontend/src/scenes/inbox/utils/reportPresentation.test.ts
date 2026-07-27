import { latestChartPerId } from '../logics/inboxReportDetailLogic'
import { SignalReportArtefact } from '../types'

describe('report chart presentation', () => {
    function chartArtefact(chartId: string, title: string, createdAt: string): SignalReportArtefact {
        return {
            id: `${chartId}-${createdAt}`,
            type: 'chart',
            created_at: createdAt,
            content: { chart_id: chartId, title, query: { kind: 'InsightVizNode' } },
        } as unknown as SignalReportArtefact
    }

    describe('latestChartPerId', () => {
        it('keeps the newest version of a re-supplied id, at the position it first appeared', () => {
            // A refresh appends rather than replacing, so the log holds both versions of `alpha`.
            const charts = latestChartPerId([
                chartArtefact('alpha', 'Alpha v1', '2026-01-01T00:00:00Z'),
                chartArtefact('beta', 'Beta', '2026-01-02T00:00:00Z'),
                chartArtefact('alpha', 'Alpha v2', '2026-01-03T00:00:00Z'),
            ])

            expect(charts.map((c) => c.title)).toEqual(['Alpha v2', 'Beta'])
        })

        it('ignores artefacts that are not charts', () => {
            const note = { id: 'n1', type: 'note', created_at: '2026-01-01T00:00:00Z', content: { note: 'hi' } }
            const charts = latestChartPerId([
                note as unknown as SignalReportArtefact,
                chartArtefact('alpha', 'Alpha', '2026-01-02T00:00:00Z'),
            ])

            expect(charts.map((c) => c.chart_id)).toEqual(['alpha'])
        })
    })
})
