import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { metaLogic } from 'scenes/session-recordings/player/metaLogic'
import recordingMetaJson from '../__mocks__/recording_meta.json'
import recordingEventsJson from '../__mocks__/recording_events.json'
import { useMocks } from '~/mocks/jest'
import { sessionRecordingsTableLogic } from '../sessionRecordingsTableLogic'

const playerProps = { sessionRecordingId: '1', playerKey: 'playlist' }

describe('metaLogic', () => {
    let logic: ReturnType<typeof metaLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/session_recordings/:id': { result: recordingMetaJson },
                '/api/projects/:team/events': { results: recordingEventsJson },
            },
        })
        initKeaTests()
        logic = metaLogic(playerProps)
        logic.mount()
    })

    describe('core assumptions', () => {
        it('mounts other logics', () => {
            expectLogic(logic).toMount([
                sessionRecordingDataLogic(playerProps),
                sessionRecordingPlayerLogic(playerProps),
            ])
        })
        it('starts with loading state', () => {
            expectLogic(logic).toMatchValues({
                loading: true,
            })
        })
    })

    describe('loading state', () => {
        it('stops loading after meta load is successful', async () => {
            await expectLogic(logic, () => {
                sessionRecordingDataLogic(playerProps).actions.loadRecordingMeta()
            })
                .toDispatchActions(['loadRecordingMetaSuccess'])
                .toMatchValues({ loading: false })
        })
    })

    describe('interacts with recording lists', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/:team/session_recordings': () => {
                        return [
                            200,
                            {
                                results: [{ id: '1', person: { name: 'John Doe' }, start_time: 1600000000000 }],
                            },
                        ]
                    },
                },
            })
            sessionRecordingsTableLogic().mount()
        })
        it('grabs person data from the recording list until metadata is loaded', async () => {
            // Make the metadata fetch fail
            logic.unmount()
            useMocks({
                get: {
                    '/api/projects/:team/session_recordings/:id': () => [500, { status: 0 }],
                },
            })
            logic.mount()

            await expectLogic(sessionRecordingsTableLogic, () => {
                sessionRecordingsTableLogic.actions.getSessionRecordings()
            }).toDispatchActions(['getSessionRecordingsSuccess'])
            // Before recording metadata is loaded, the person data should be from the recording list
            expectLogic(logic).toMatchValues({ sessionPerson: { name: 'John Doe' } })

            // Fix the metadata fetch failure
            logic.unmount()
            useMocks({
                get: {
                    '/api/projects/:team/session_recordings/:id': { result: recordingMetaJson },
                },
            })
            logic.mount()

            // After recording metadata is loaded, the person data should be from the recording list
            await expectLogic(logic, () => {
                sessionRecordingDataLogic(playerProps).actions.loadRecordingMeta()
            })
                .toDispatchActions(['loadRecordingMetaSuccess'])
                .toMatchValues({
                    sessionPerson: {
                        id: 1,
                        name: 'alex@posthog.com',
                        distinct_ids: [
                            'qajhF5PVpNmK4N8etdbXjpduRR076loSNxcNh68jPVV',
                            '17d9d2f97b05de-0bc291cd42d2be-1c306851-1fa400-17d9d2f97b1b38',
                        ],
                        properties: {
                            $os: 'Mac OS X',
                            email: 'alex@posthog.com',
                            $browser: 'Chrome',
                            $initial_os: 'Mac OS X',
                        },
                        created_at: '2021-12-09T03:14:41.757000Z',
                        uuid: '017d9d2f-995c-0000-5602-dcfdeff46fc0',
                    },
                })
        })

        it('grabs recordingStartTime from the recording list until metadata is loaded', async () => {
            // Make the metadata fetch fail
            logic.unmount()
            useMocks({
                get: {
                    '/api/projects/:team/session_recordings/:id': () => [500, { status: 0 }],
                },
            })
            logic.mount()

            await expectLogic(sessionRecordingsTableLogic, () => {
                sessionRecordingsTableLogic.actions.getSessionRecordings()
            }).toDispatchActions(['getSessionRecordingsSuccess'])
            // Before recording metadata is loaded, the person data should be from the recording list
            expectLogic(logic).toMatchValues({ recordingStartTime: 1600000000000 })

            // Fix the metadata fetch failure
            logic.unmount()
            useMocks({
                get: {
                    '/api/projects/:team/session_recordings/:id': { result: recordingMetaJson },
                },
            })
            logic.mount()

            // After recording metadata is loaded, the startTime should be from the recording list
            await expectLogic(logic, () => {
                sessionRecordingDataLogic(playerProps).actions.loadRecordingMeta()
            })
                .toDispatchActions(['loadRecordingMetaSuccess'])
                .toMatchValues({
                    recordingStartTime: 1639078619223,
                })
        })
    })
})
