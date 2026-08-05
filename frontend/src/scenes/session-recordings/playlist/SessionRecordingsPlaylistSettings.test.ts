import { RecordingUniversalFilters } from '~/types'

import { getSortChangedEvent } from './SessionRecordingsPlaylistSettings'

type Sort = Parameters<typeof getSortChangedEvent>[1]

const filters = (order?: string, order_direction?: 'ASC' | 'DESC'): RecordingUniversalFilters =>
    ({ order, order_direction }) as RecordingUniversalFilters

describe('getSortChangedEvent', () => {
    it('returns null when the sort is unchanged so no-op clicks are not logged', () => {
        expect(
            getSortChangedEvent(filters('start_time', 'DESC'), { order: 'start_time', order_direction: 'DESC' })
        ).toBeNull()
    })

    const cases: [string, RecordingUniversalFilters, Sort, Record<string, string>][] = [
        [
            'the order changes',
            filters('start_time', 'DESC'),
            { order: 'activity_score', order_direction: 'DESC' },
            {
                sort_key: 'activity_score',
                sort_direction: 'DESC',
                previous_sort_key: 'start_time',
                previous_sort_direction: 'DESC',
            },
        ],
        [
            'only the direction changes',
            filters('start_time', 'DESC'),
            { order: 'start_time', order_direction: 'ASC' },
            {
                sort_key: 'start_time',
                sort_direction: 'ASC',
                previous_sort_key: 'start_time',
                previous_sort_direction: 'DESC',
            },
        ],
        [
            'a user switches away from relevance',
            filters('surfacing_score', 'DESC'),
            { order: 'start_time', order_direction: 'DESC' },
            {
                sort_key: 'start_time',
                sort_direction: 'DESC',
                previous_sort_key: 'surfacing_score',
                previous_sort_direction: 'DESC',
            },
        ],
        [
            'filters carry no explicit sort yet',
            filters(undefined, undefined),
            { order: 'surfacing_score', order_direction: 'DESC' },
            {
                sort_key: 'surfacing_score',
                sort_direction: 'DESC',
                previous_sort_key: 'start_time',
                previous_sort_direction: 'DESC',
            },
        ],
    ]

    it.each(cases)('captures previous and new sort when %s', (_name, currentFilters, sort, expected) => {
        expect(getSortChangedEvent(currentFilters, sort)).toEqual(expected)
    })
})
