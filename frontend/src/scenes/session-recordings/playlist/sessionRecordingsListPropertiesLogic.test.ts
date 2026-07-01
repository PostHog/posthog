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

describe('sessionRecordingsListPropertiesLogic', () => {
    let logic: ReturnType<typeof sessionRecordingsListPropertiesLogic.build>
    let issuedQueries: string[]

    beforeEach(() => {
        issuedQueries = []
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': {
                    results: [
                        ['s1', 'AU', 'Chrome', 'Desktop', 'Windows', 'Windows 10', 'google.com'],
                        ['s2', 'GB', 'Safari', 'Mobile', 'iOS', 'iOS 14', 'google.com'],
                    ],
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
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': async (info: any) => {
                    const body = await info.request.json()
                    issuedQueries.push(body.query.query)
                    return {
                        results: [
                            [
                                's1',
                                'AU',
                                'Chrome',
                                'Desktop',
                                'Windows',
                                'Windows 10',
                                'google.com',
                                null,
                                null,
                                null,
                                'paid',
                                'Paid Search',
                            ],
                        ],
                    }
                },
            },
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

        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': {
                    results: [
                        [
                            's1',
                            'AU',
                            'Chrome',
                            'Desktop',
                            'Windows',
                            'Windows 10',
                            'google.com',
                            null,
                            null,
                            null,
                            'paid',
                        ],
                    ],
                },
            },
        })
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
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': async (info: any) => {
                    const body = await info.request.json()
                    if (body.query.query.includes('$entry_utm_medium')) {
                        return [500, { detail: 'unknown field' }]
                    }
                    return {
                        results: [['s1', 'AU', 'Chrome', 'Desktop', 'Windows', 'Windows 10', 'google.com']],
                    }
                },
            },
        })
        sessionRecordingPinnedPropertiesLogic.actions.setPinnedProperties(['$entry_utm_medium'])

        await expectLogic(logic, () => {
            logic.actions.loadPropertiesForSessions([mockSessons[0]])
        }).toDispatchActions(['loadPropertiesForSessionsSuccess'])

        expect(logic.values.recordingPropertiesById['s1']).toMatchObject({
            $browser: 'Chrome',
            $entry_utm_medium: null,
        })

        // the null placeholder marks the cache entry complete, so no refetch loop
        await expectLogic(logic, () => {
            logic.actions.maybeLoadPropertiesForSessions([mockSessons[0]])
        }).toNotHaveDispatchedActions(['loadPropertiesForSessions'])
    })
})
