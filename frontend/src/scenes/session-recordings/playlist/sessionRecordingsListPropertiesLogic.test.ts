import { expectLogic } from 'kea-test-utils'
import { sessionRecordingsListPropertiesLogic } from 'scenes/session-recordings/playlist/sessionRecordingsListPropertiesLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SessionRecordingType } from '~/types'

const mockSessons: SessionRecordingType[] = [
    {
        id: 's1',
        start_time: '2021-01-01T00:00:00Z',
        end_time: '2021-01-01T01:00:00Z',
        viewed: false,
        recording_duration: 0,
    },
    {
        id: 's2',
        start_time: '2021-01-01T02:00:00Z',
        end_time: '2021-01-01T03:00:00Z',
        viewed: false,
        recording_duration: 0,
    },

    {
        id: 's3',
        start_time: '2021-01-01T03:00:00Z',
        end_time: '2021-01-01T04:00:00Z',
        viewed: false,
        recording_duration: 0,
    },
]

describe('sessionRecordingsListPropertiesLogic', () => {
    let logic: ReturnType<typeof sessionRecordingsListPropertiesLogic.build>

    beforeEach(() => {
        useMocks({
            post: {
                '/api/projects/:team/query': {
                    results: [
                        ['s1', JSON.stringify({ blah: 'blah1' })],
                        ['s2', JSON.stringify({ blah: 'blah2' })],
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
            recordingProperties: [
                { id: 's1', properties: { blah: 'blah1' } },
                { id: 's2', properties: { blah: 'blah2' } },
            ],
            recordingPropertiesById: {
                s1: { blah: 'blah1' },
                s2: { blah: 'blah2' },
            },
        })
    })

    it('does not loads cached properties', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadPropertiesForSessions(mockSessons)
        }).toDispatchActions(['loadPropertiesForSessionsSuccess'])

        expect(logic.values).toMatchObject({
            recordingPropertiesById: {
                s1: { blah: 'blah1' },
                s2: { blah: 'blah2' },
            },
        })

        await expectLogic(logic, () => {
            logic.actions.maybeLoadPropertiesForSessions(mockSessons)
        }).toNotHaveDispatchedActions(['loadPropertiesForSessionsSuccess'])

        expect(logic.values).toMatchObject({
            recordingPropertiesById: {
                s1: { blah: 'blah1' },
                s2: { blah: 'blah2' },
            },
        })
    })
})
