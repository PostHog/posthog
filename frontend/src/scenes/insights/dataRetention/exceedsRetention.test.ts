import { NodeKind } from '~/queries/schema/schema-general'

import { exceedsRetention } from './exceedsRetention'

const RETENTION_MONTHS = 12

const insightViz = (dateFrom: string | null): any => ({
    kind: NodeKind.InsightVizNode,
    source: { kind: NodeKind.TrendsQuery, dateRange: { date_from: dateFrom } },
})

const sqlInsight = (query: string): any => ({
    kind: NodeKind.DataVisualizationNode,
    source: { kind: NodeKind.HogQLQuery, query },
})

describe('exceedsRetention', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2026-06-15T12:00:00.000Z'))
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each([
        ['a team with no enforced window never warns', insightViz('-3y'), undefined, null, false],
        ['a range inside the window is fine', insightViz('-30d'), undefined, RETENTION_MONTHS, false],
        ['a range past the window warns', insightViz('-3y'), undefined, RETENTION_MONTHS, true],
        ['"all time" warns however short the window', insightViz('all'), undefined, 84, true],
        ['an absolute date past the window warns', insightViz('2020-01-01'), undefined, RETENTION_MONTHS, true],
        ['a query with no range at all stays quiet', insightViz(null), undefined, RETENTION_MONTHS, false],
        ['an unparseable range stays quiet', insightViz('not-a-date'), undefined, RETENTION_MONTHS, false],
        // The precedence the dashboard banner and a tile's icon both depend on: whatever the surface passes in
        // wins over the range saved on the insight, in both directions.
        ['an override shortens a long saved range', insightViz('-3y'), '-7d', RETENTION_MONTHS, false],
        ['an override lengthens a short saved range', insightViz('-7d'), '-3y', RETENTION_MONTHS, true],
        ['no override falls back to the saved range', insightViz('-3y'), undefined, RETENTION_MONTHS, true],
        // SQL can scan arbitrary history and carries no range we can resolve, so reading events is the signal.
        ['SQL reading events warns', sqlInsight('select count() from events'), undefined, RETENTION_MONTHS, true],
        ['SQL not reading events stays quiet', sqlInsight('select 1'), undefined, RETENTION_MONTHS, false],
        [
            'SQL over persons only stays quiet',
            sqlInsight('select count() from persons'),
            undefined,
            RETENTION_MONTHS,
            false,
        ],
        ['SQL ignores any override it was handed', sqlInsight('select 1'), 'all', RETENTION_MONTHS, false],
    ])(
        '%s',
        (
            _label: string,
            query: any,
            dateFromOverride: string | undefined,
            retentionMonths: number | null,
            expected: boolean
        ) => {
            expect(exceedsRetention({ query, dateFromOverride, retentionMonths })).toBe(expected)
        }
    )
})
