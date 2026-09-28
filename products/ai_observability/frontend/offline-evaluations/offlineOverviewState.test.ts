import {
    offlineFiltersFromUrl,
    offlinePreferencesKey,
    readOfflineScorerPreferences,
    saveOfflineScorerPreferences,
} from './offlineOverviewState'

const first = '11111111-1111-4111-8111-111111111111'
const second = '22222222-2222-4222-8222-222222222222'

describe('offline overview preferences', () => {
    beforeEach(() => localStorage.clear())

    it('persists chart order only in the same user and environment', () => {
        saveOfflineScorerPreferences(1, 2, [second, first])
        expect(readOfflineScorerPreferences(1, 2)).toEqual([second, first])
        expect(readOfflineScorerPreferences(2, 2)).toBeNull()
        expect(readOfflineScorerPreferences(1, 3)).toBeNull()
        saveOfflineScorerPreferences(1, 2, [])
        expect(readOfflineScorerPreferences(1, 2)).toEqual([])
    })

    it.each(['broken', '{}', '{"version":2,"scorerIds":[]}', '{"version":1,"scorerIds":["not-a-uuid"]}'])(
        'ignores malformed or unsupported stored preferences: %s',
        (raw) => {
            localStorage.setItem(offlinePreferencesKey(1, 2), raw)
            expect(readOfflineScorerPreferences(1, 2)).toBeNull()
        }
    )

    it('keeps URL input limited to supported list filters', () => {
        expect(
            offlineFiltersFromUrl({
                search: 'check',
                suite_key: 'a',
                cursor: 'old',
                limit: 500,
                scores: first,
                model_version: ['bad'],
                statuses: '',
            })
        ).toEqual({ search: 'check', suite_key: 'a' })
    })
})
