import { expectLogic } from 'kea-test-utils'

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

    beforeEach(() => {
        useMocks({
            post: {
                '/api/environments/:team_id/query': {
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
})
