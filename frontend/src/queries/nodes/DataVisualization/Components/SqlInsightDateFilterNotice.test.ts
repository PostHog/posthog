import { DateRange, HogQLQuery, NodeKind } from '~/queries/schema/schema-general'

import { isAffectedByDateFilterResolutionChange } from './SqlInsightDateFilterNotice'

function hogQLQuery(query: string, filters?: HogQLQuery['filters']): HogQLQuery {
    return { kind: NodeKind.HogQLQuery, query, filters }
}

const FILTERED_SQL = 'SELECT count() FROM demo WHERE ts >= {filters.dateRange.from} AND ts <= {filters.dateRange.to}'

describe('isAffectedByDateFilterResolutionChange', () => {
    it.each<[string, DateRange, boolean]>([
        // affected: relative day-or-coarser date_from snaps to midnight
        ['relative month start', { date_from: 'mStart', date_to: null }, true],
        ['relative days with explicit datetime end', { date_from: '-7d', date_to: '2026-07-24T23:59:59' }, true],
        ['relative week start', { date_from: 'wStart', date_to: null }, true],
        // affected: open-ended ranges gain an end-of-today upper bound
        ['absolute start with no end', { date_from: '2026-07-01', date_to: null }, true],
        // affected: date-only or relative date_to now covers the whole day
        ['date-only end', { date_from: '2026-07-01', date_to: '2026-07-24' }, true],
        ['relative end', { date_from: '2026-07-01', date_to: '-3d' }, true],
        // unaffected: "all" and sub-day rolling windows are exempt from the fix
        ['all time with no end', { date_from: 'all', date_to: null }, false],
        ['rolling hour window', { date_from: '-1h', date_to: null }, false],
        ['rolling minute window', { date_from: '-30M', date_to: null }, false],
        // unaffected: explicit datetimes are used verbatim
        ['absolute start and datetime end', { date_from: '2026-07-01', date_to: '2026-07-24T23:59:59' }, false],
        // unaffected: no date filter in use
        ['empty date range', { date_from: null, date_to: null }, false],
        // explicitDate disables the end-of-day snapping of date_to only; date_from still snaps
        [
            'explicit date with date-only end',
            { date_from: '2026-07-01', date_to: '2026-07-24', explicitDate: true },
            false,
        ],
        ['explicit date with no end', { date_from: '2026-07-01', date_to: null, explicitDate: true }, true],
        ['explicit date with relative preset', { date_from: '-1mStart', date_to: '-1mEnd', explicitDate: true }, true],
    ])('%s -> %s', (_name, dateRange, expected) => {
        expect(isAffectedByDateFilterResolutionChange(hogQLQuery(FILTERED_SQL, { dateRange }))).toBe(expected)
    })

    it('is unaffected without a filters placeholder or date range', () => {
        expect(
            isAffectedByDateFilterResolutionChange(
                hogQLQuery('SELECT count() FROM demo', { dateRange: { date_from: 'mStart' } })
            )
        ).toBe(false)
        expect(isAffectedByDateFilterResolutionChange(hogQLQuery(FILTERED_SQL))).toBe(false)
    })
})
