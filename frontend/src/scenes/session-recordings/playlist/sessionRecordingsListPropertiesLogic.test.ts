import { expectLogic } from 'kea-test-utils'

import { sessionRecordingPinnedPropertiesLogic } from 'scenes/session-recordings/player/player-meta/sessionRecordingPinnedPropertiesLogic'
import { sessionRecordingsListPropertiesLogic } from 'scenes/session-recordings/playlist/sessionRecordingsListPropertiesLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SessionRecordingType } from '~/types'

const EXPECTED_RECORDING_PROPERTIES = [
    {
        id: 's1',
        properties: {
            $browser: 'Chrome',
            $device_type: 'Desktop',
            $geoip_country_code: 'AU',
            $os: 'Windows',
            $os_name: 'Windows 10',
            $entry_referring_domain: 'google.com',
        },
    },
    {
        id: 's2',
        properties: {
            $browser: 'Safari',
            $device_type: 'Mobile',
            $geoip_country_code: 'GB',
            $os: 'iOS',
            $os_name: 'iOS 14',
            $entry_referring_domain: 'google.com',
        },
    },
]

const EXPECTED_RECORDING_PROPERTIES_BY_ID = {
    s1: {
        $browser: 'Chrome',
        $device_type: 'Desktop',
        $geoip_country_code: 'AU',
        $os: 'Windows',
        $os_name: 'Windows 10',
        $entry_referring_domain: 'google.com',
    },
    s2: {
        $browser: 'Safari',
        $device_type: 'Mobile',
        $geoip_country_code: 'GB',
        $os: 'iOS',
        $os_name: 'iOS 14',
        $entry_referring_domain: 'google.com',
    },
}

const mockSessons: SessionRecordingType[] = [
    {
        id: 's1',
        start_time: '2021-01-01T00:00:00Z',
        end_time: '2021-01-01T01:00:00Z',
        viewed: false,
        viewers: [],
        recording_duration: 0,
        snapshot_source: 'web',
    },
    {
        id: 's2',
        start_time: '2021-01-01T02:00:00Z',
        end_time: '2021-01-01T03:00:00Z',
        viewed: false,
        viewers: [],
        recording_duration: 0,
        snapshot_source: 'mobile',
    },

    {
        id: 's3',
        start_time: '2021-01-01T03:00:00Z',
        end_time: '2021-01-01T04:00:00Z',
        viewed: false,
        viewers: [],
        recording_duration: 0,
        snapshot_source: 'unknown',
    },
]

// matches the order of the base columns in the properties query, after the leading session_id
const S1_BASE_ROW = ['s1', 'AU', 'Chrome', 'Desktop', 'Windows', 'Windows 10', 'google.com', null, null, null]
const S2_BASE_ROW = ['s2', 'GB', 'Safari', 'Mobile', 'iOS', 'iOS 14', 'google.com', null, null, null]

// mock the query endpoint with a per-request handler that receives the HogQL query string
const useQueryMocks = (handler: (query: string) => unknown): void => {
    useMocks({
        post: {
            '/api/environments/:team_id/query/:kind': async (info: any) => {
                const body = await info.request.json()
                return handler(body.query.query)
            },
        },
    })
}

describe('sessionRecordingsListPropertiesLogic', () => {
    let logic: ReturnType<typeof sessionRecordingsListPropertiesLogic.build>

    beforeEach(() => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': {
                    results: [S1_BASE_ROW, S2_BASE_ROW],
                },
            },
        })
        initKeaTests()
    })

    beforeEach(() => {
        logic = sessionRecordingsListPropertiesLogic()
        logic.mount()
        sessionRecordingPinnedPropertiesLogic.actions.setPinnedProperties([])
    })

    it('loads properties', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadPropertiesForSessions(mockSessons)
        }).toDispatchActions(['loadPropertiesForSessionsSuccess'])

        expect(logic.values).toMatchObject({
            recordingProperties: EXPECTED_RECORDING_PROPERTIES,
            recordingPropertiesById: EXPECTED_RECORDING_PROPERTIES_BY_ID,
        })
    })

    it('does not loads cached properties', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadPropertiesForSessions(mockSessons)
        }).toDispatchActions(['loadPropertiesForSessionsSuccess'])

        expect(logic.values).toMatchObject({
            recordingPropertiesById: EXPECTED_RECORDING_PROPERTIES_BY_ID,
        })

        await expectLogic(logic, () => {
            logic.actions.maybeLoadPropertiesForSessions(mockSessons)
        }).toNotHaveDispatchedActions(['loadPropertiesForSessionsSuccess'])

        expect(logic.values).toMatchObject({
            recordingPropertiesById: EXPECTED_RECORDING_PROPERTIES_BY_ID,
        })
    })

    it('fetches pinned session properties alongside the base properties', async () => {
        const issuedQueries: string[] = []
        useQueryMocks((query) => {
            issuedQueries.push(query)
            return { results: [[...S1_BASE_ROW, 'paid', 'Paid Search']] }
        })

        sessionRecordingPinnedPropertiesLogic.actions.setPinnedProperties([
            'Start',
            'email',
            '$entry_utm_medium',
            '$channel_type',
        ])

        await expectLogic(logic, () => {
            logic.actions.loadPropertiesForSessions([mockSessons[0]])
        }).toDispatchActions(['loadPropertiesForSessionsSuccess'])

        expect(issuedQueries).toHaveLength(1)
        expect(issuedQueries[0]).toContain('any(session.$entry_utm_medium) as $entry_utm_medium')
        expect(issuedQueries[0]).toContain('any(session.$channel_type) as $channel_type')
        // non-session pins must not leak into the query
        expect(issuedQueries[0]).not.toContain('email')
        expect(issuedQueries[0]).not.toContain('Start')

        expect(logic.values.recordingPropertiesById['s1']).toMatchObject({
            $browser: 'Chrome',
            $entry_utm_medium: 'paid',
            $channel_type: 'Paid Search',
        })
    })

    it('refetches cached sessions that are missing newly pinned session properties', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadPropertiesForSessions(mockSessons)
        }).toDispatchActions(['loadPropertiesForSessionsSuccess'])

        useQueryMocks(() => ({ results: [[...S1_BASE_ROW, 'paid']] }))
        sessionRecordingPinnedPropertiesLogic.actions.setPinnedProperties(['$entry_utm_medium'])

        await expectLogic(logic, () => {
            logic.actions.maybeLoadPropertiesForSessions([mockSessons[0]])
        }).toDispatchActions(['loadPropertiesForSessionsSuccess'])

        expect(logic.values.recordingPropertiesById['s1']).toMatchObject({ $entry_utm_medium: 'paid' })

        await expectLogic(logic, () => {
            logic.actions.maybeLoadPropertiesForSessions([mockSessons[0]])
        }).toNotHaveDispatchedActions(['loadPropertiesForSessions'])
    })

    it('falls back to the base properties when a pinned session property fails to query', async () => {
        const issuedQueries: string[] = []
        useQueryMocks((query) => {
            issuedQueries.push(query)
            if (query.includes('$entry_utm_medium')) {
                return [400, { detail: 'unknown field' }]
            }
            return {
                results: [query.includes('$channel_type') ? [...S1_BASE_ROW, 'Paid Search'] : S1_BASE_ROW],
            }
        })

        // a queryable pin loads fine on its own
        sessionRecordingPinnedPropertiesLogic.actions.setPinnedProperties(['$channel_type'])
        await expectLogic(logic, () => {
            logic.actions.loadPropertiesForSessions([mockSessons[0]])
        }).toDispatchActions(['loadPropertiesForSessionsSuccess'])
        expect(logic.values.recordingPropertiesById['s1']).toMatchObject({ $channel_type: 'Paid Search' })

        // adding an unqueryable pin fails the wide query and falls back to the base one
        sessionRecordingPinnedPropertiesLogic.actions.setPinnedProperties(['$channel_type', '$entry_utm_medium'])
        await expectLogic(logic, () => {
            logic.actions.maybeLoadPropertiesForSessions([mockSessons[0]])
        }).toDispatchActions(['loadPropertiesForSessionsSuccess'])

        // cached values survive the fallback and the failed pin reads as complete (null), so no refetch loop
        expect(logic.values.recordingPropertiesById['s1']).toMatchObject({
            $browser: 'Chrome',
            $channel_type: 'Paid Search',
            $entry_utm_medium: null,
        })
        await expectLogic(logic, () => {
            logic.actions.maybeLoadPropertiesForSessions([mockSessons[0]])
        }).toNotHaveDispatchedActions(['loadPropertiesForSessions'])

        // the failed pin set is remembered: new sessions load with a single base query
        const queriesSoFar = issuedQueries.length
        await expectLogic(logic, () => {
            logic.actions.maybeLoadPropertiesForSessions([mockSessons[1]])
        }).toDispatchActions(['loadPropertiesForSessionsSuccess'])
        expect(issuedQueries).toHaveLength(queriesSoFar + 1)
        expect(issuedQueries[issuedQueries.length - 1]).not.toContain('$entry_utm_medium')
    })

    it('retries the extended query after a transient failure', async () => {
        const issuedQueries: string[] = []
        let failWideQuery = true
        useQueryMocks((query) => {
            issuedQueries.push(query)
            if (query.includes('$entry_utm_medium')) {
                if (failWideQuery) {
                    return [500, { detail: 'timeout' }]
                }
                return { results: [[...S2_BASE_ROW, 'paid']] }
            }
            return { results: [S1_BASE_ROW] }
        })
        sessionRecordingPinnedPropertiesLogic.actions.setPinnedProperties(['$entry_utm_medium'])

        await expectLogic(logic, () => {
            logic.actions.loadPropertiesForSessions([mockSessons[0]])
        }).toDispatchActions(['loadPropertiesForSessionsSuccess'])

        // a 5xx does not mark the pin set unqueryable — the next batch retries the wide query
        failWideQuery = false
        await expectLogic(logic, () => {
            logic.actions.maybeLoadPropertiesForSessions([mockSessons[1]])
        }).toDispatchActions(['loadPropertiesForSessionsSuccess'])

        expect(issuedQueries[issuedQueries.length - 1]).toContain('$entry_utm_medium')
        expect(logic.values.recordingPropertiesById['s2']).toMatchObject({ $entry_utm_medium: 'paid' })
    })
})
