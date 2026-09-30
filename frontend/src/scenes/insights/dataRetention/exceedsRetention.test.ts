import { NodeKind } from '~/queries/schema/schema-general'

import { exceedsRetention } from './exceedsRetention'

const RETENTION_MONTHS = 12

const insightViz = (dateFrom: string | null, series: any[] = [{ kind: NodeKind.EventsNode }]): any => ({
    kind: NodeKind.InsightVizNode,
    source: { kind: NodeKind.TrendsQuery, dateRange: { date_from: dateFrom }, series },
})

const WAREHOUSE_SERIES = { kind: NodeKind.DataWarehouseNode }

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
        ['a team with no enforced window never warns', insightViz('-3y'), undefined, '2023-06-15', null, false],
        [
            'a resolved range inside the window is fine',
            insightViz('-30d'),
            undefined,
            '2026-05-16',
            RETENTION_MONTHS,
            false,
        ],
        ['a resolved range past the window warns', insightViz('-3y'), undefined, '2023-06-15', RETENTION_MONTHS, true],
        ['no resolved range yet stays quiet', insightViz('-3y'), undefined, undefined, RETENTION_MONTHS, false],
        // "All time" resolves to the earliest event the floored query can see, so the resolved range never reaches
        // past the window; the requested range has to carry the warning.
        ['"all time" warns however recent the resolved range', insightViz('all'), undefined, '2026-01-01', 84, true],
        [
            'an "all time" override warns over a short saved range',
            insightViz('-7d'),
            'all',
            '2026-06-08',
            RETENTION_MONTHS,
            true,
        ],
        [
            'an override narrower than a saved "all time" defers to the resolved range',
            insightViz('all'),
            '-7d',
            '2026-06-08',
            RETENTION_MONTHS,
            false,
        ],
        ['SQL warns whenever retention applies', sqlInsight('select 1'), undefined, undefined, RETENTION_MONTHS, true],
        [
            'a warehouse-only insight never warns',
            insightViz('all', [WAREHOUSE_SERIES]),
            undefined,
            '2023-06-15',
            RETENTION_MONTHS,
            false,
        ],
        [
            'a mixed events and warehouse insight warns',
            insightViz('-3y', [{ kind: NodeKind.EventsNode }, WAREHOUSE_SERIES]),
            undefined,
            '2023-06-15',
            RETENTION_MONTHS,
            true,
        ],
    ])(
        '%s',
        (
            _label: string,
            query: any,
            dateFromOverride: string | undefined,
            resolvedDateFrom: string | undefined,
            retentionMonths: number | null,
            expected: boolean
        ) => {
            expect(exceedsRetention({ query, dateFromOverride, resolvedDateFrom, retentionMonths })).toBe(expected)
        }
    )
})
