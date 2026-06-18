import { TeamType } from '~/types'

import { HOGQL_COLUMNS_KEY, getDefaultEventsQueryForTeam } from './defaultEventsQuery'

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
