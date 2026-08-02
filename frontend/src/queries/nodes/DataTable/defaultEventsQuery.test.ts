import { EventsQuery, NodeKind } from '~/queries/schema/schema-general'
import { TeamType } from '~/types'

import { HOGQL_COLUMNS_KEY, applyEventsViewPreset, getDefaultEventsQueryForTeam } from './defaultEventsQuery'

describe('getDefaultEventsQueryForTeam', () => {
    it('returns null when live_events_columns is unset', () => {
        expect(getDefaultEventsQueryForTeam({} as Partial<TeamType>)).toBeNull()
    })

    it.each([
        {
            name: 'prepends * for HOGQL columns that do not include it',
            columns: [HOGQL_COLUMNS_KEY, 'event', 'timestamp'],
            expectedSelect: ['*', 'event', 'timestamp'],
            expectedOrderBy: ['timestamp DESC'],
        },
        {
            name: 'does not duplicate * when HOGQL columns already include it',
            columns: [HOGQL_COLUMNS_KEY, '*', 'event', 'timestamp'],
            expectedSelect: ['*', 'event', 'timestamp'],
            expectedOrderBy: ['timestamp DESC'],
        },
        {
            name: 'does not duplicate * for legacy columns (cleanLiveEventsColumns already adds one)',
            columns: ['event', 'url'],
            expectedSelect: [
                '*',
                'event',
                'coalesce(properties.$current_url, properties.$screen_name) -- Url / Screen',
                'timestamp',
            ],
            expectedOrderBy: ['timestamp DESC'],
        },
        {
            name: 'omits orderBy when timestamp is not in the column list',
            columns: [HOGQL_COLUMNS_KEY, 'event'],
            expectedSelect: ['*', 'event'],
            expectedOrderBy: [],
        },
    ])('$name', ({ columns, expectedSelect, expectedOrderBy }) => {
        const query = getDefaultEventsQueryForTeam({ live_events_columns: columns } as Partial<TeamType>)
        expect(query).not.toBeNull()
        expect(query!.select).toEqual(expectedSelect)
        expect(query!.orderBy).toEqual(expectedOrderBy)
        expect(query!.after).toBe('-1h')
    })
})

describe('applyEventsViewPreset', () => {
    const preset: EventsQuery = {
        kind: NodeKind.EventsQuery,
        select: ['event', 'count()'],
        after: '-1h',
        orderBy: ['count() DESC'],
    }

    // Every preset hardcodes its own `after`, so switching view used to drop whatever range the
    // user had picked and drag them back to the preset's window.
    it('keeps the date range the user picked rather than the one baked into the preset', () => {
        const result = applyEventsViewPreset(preset, { ...preset, after: '-7d', before: '-1d' })

        expect(result.after).toBe('-7d')
        expect(result.before).toBe('-1d')
    })

    it('takes the columns and ordering from the preset', () => {
        const result = applyEventsViewPreset(preset, {
            kind: NodeKind.EventsQuery,
            select: ['*', 'timestamp'],
            orderBy: ['timestamp DESC'],
            after: '-7d',
        })

        expect(result.select).toEqual(['event', 'count()'])
        expect(result.orderBy).toEqual(['count() DESC'])
    })

    it.each([true, false])('carries the test-account filter across when set to %s', (filterTestAccounts) => {
        expect(applyEventsViewPreset(preset, { ...preset, filterTestAccounts }).filterTestAccounts).toBe(
            filterTestAccounts
        )
    })

    it('falls back to the preset date range when the current query has none', () => {
        const { after: _after, ...noDates } = preset
        expect(applyEventsViewPreset(preset, noDates as EventsQuery).after).toBe('-1h')
    })
})
