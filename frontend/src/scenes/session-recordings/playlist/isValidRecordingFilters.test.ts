import { RecordingUniversalFilters } from '~/types'

import { isValidRecordingFilters } from './sessionRecordingsPlaylistLogic'

describe('isValidRecordingFilters', () => {
    it.each([
        // A query node (any `{ kind, ... }` shape) is not a recording filter set. Spreading one over the
        // defaults builds a filter that dead-ends the recordings list, so it must be rejected.
        ['an actors query node', { kind: 'ActorsQuery', source: {} }],
        ['a recordings query node', { kind: 'RecordingsQuery' }],
    ])('rejects %s', (_name, filters) => {
        expect(isValidRecordingFilters(filters as Partial<RecordingUniversalFilters>)).toBe(false)
    })

    it('accepts a well-formed recording filter set', () => {
        expect(
            isValidRecordingFilters({
                date_from: '-3d',
                date_to: null,
                filter_test_accounts: false,
                duration: [],
            } as Partial<RecordingUniversalFilters>)
        ).toBe(true)
    })
})
