import { expectLogic } from 'kea-test-utils'
import { List } from 'react-virtualized/dist/es/List'
import { initKeaTests } from '~/test/init'
import {
    DEFAULT_SCROLLING_RESET_TIME_INTERVAL,
    eventsListLogic,
} from 'scenes/session-recordings/player/eventsListLogic'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { sharedListLogic } from 'scenes/session-recordings/player/sharedListLogic'
import { useMocks } from '~/mocks/jest'
import recordingSnapshotsJson from 'scenes/session-recordings/__mocks__/recording_snapshots.json'
import recordingMetaJson from 'scenes/session-recordings/__mocks__/recording_meta.json'
import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events.json'

describe('eventsListLogic', () => {
    let logic: ReturnType<typeof eventsListLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/session_recordings/:id/snapshots': { result: recordingSnapshotsJson },
                '/api/projects/:team/session_recordings/:id': { result: recordingMetaJson },
                '/api/projects/:team/events': { results: recordingEventsJson },
            },
        })
        initKeaTests()
        logic = eventsListLogic()
        logic.mount()
    })

    describe('core assumptions', () => {
        it('mounts other logics', async () => {
            await expectLogic(logic).toMount([
                sessionRecordingDataLogic,
                sessionRecordingPlayerLogic,
                eventUsageLogic,
                sharedListLogic,
            ])
        })
    })

    describe('setLocalFilter', () => {
        it('calls setFilter in parent logic with debounce', async () => {
            const filters = { query: 'mini pretzels' }
            await expectLogic(logic, () => {
                logic.actions.setLocalFilters({ query: 'no mini pretzels' })
                logic.actions.setLocalFilters(filters)
            })
                .toNotHaveDispatchedActions([
                    sessionRecordingDataLogic.actionCreators.setFilters({ query: 'no mini pretzels' }),
                ])
                .toDispatchActions([sessionRecordingDataLogic.actionCreators.setFilters(filters)])
        })
    })

    describe('handle event click', () => {
        it('happy case', async () => {
            const playerPosition = {
                windowId: 'window-id',
                time: 10000,
            }
            await expectLogic(logic, () => {
                logic.actions.handleEventClick(playerPosition)
            }).toDispatchActions(['handleEventClick', sessionRecordingPlayerLogic.actionCreators.seek(playerPosition)])
        })

        const nanInputs: Record<string, any> = {
            null: null,
            undefined: undefined,
            '00:00:00': '00:00:00',
            '2021-11-18T21:03:48.305000Z': '2021-11-18T21:03:48.305000Z',
        }

        Object.entries(nanInputs).forEach(([key, value]) => {
            it(`NaN case: ${key}`, async () => {
                await expectLogic(logic, async () => {
                    logic.actions.handleEventClick({
                        windowId: 'window-id',
                        time: value,
                    })
                })
                    .toDispatchActions(['handleEventClick'])
                    .toNotHaveDispatchedActions([sessionRecordingPlayerLogic.actionCreators.seek(value)])
            })
        })
    })

    describe('current position finder', () => {
        it('disable position finder from showing with debounce on scroll to', async () => {
            await expectLogic(logic, () => {
                logic.actions.scrollTo()
                logic.actions.scrollTo()
            })
                .toDispatchActions(['scrollTo', 'scrollTo', 'enablePositionFinder'])
                .toNotHaveDispatchedActions(['scrollTo', 'enablePositionFinder'])
                .toMatchValues({
                    shouldHidePositionFinder: false,
                })
        })
        it('disable position finder from showing with delay on scroll to', async () => {
            await expectLogic(logic, () => {
                logic.actions.scrollTo()
            })
                .toDispatchActions(['scrollTo'])
                .toMatchValues({
                    shouldHidePositionFinder: true,
                })
                .delay(DEFAULT_SCROLLING_RESET_TIME_INTERVAL / 4) // still hidden
                .toMatchValues({
                    shouldHidePositionFinder: true,
                })
                .delay(DEFAULT_SCROLLING_RESET_TIME_INTERVAL + 100) // buffer time
                .toDispatchActions(['enablePositionFinder'])
                .toMatchValues({
                    shouldHidePositionFinder: false,
                })
        })
        it('scroll to specific rowIndex', async () => {
            const mockedList = {
                scrollToPosition: jest.fn(),
                getOffsetForRow: jest.fn(({}: { alignment: string; index: number }) => 40),
            }

            await expectLogic(logic, async () => {
                logic.actions.setList(mockedList as unknown as List)
                logic.actions.scrollTo(10)
            }).toDispatchActions([eventUsageLogic.actionCreators.reportRecordingScrollTo(10)])

            expect(mockedList.getOffsetForRow.mock.calls.length).toBe(1)
            expect(mockedList.getOffsetForRow.mock.calls[0][0]).toEqual({ alignment: 'center', index: 10 })
            expect(mockedList.scrollToPosition.mock.calls.length).toBe(1)
            expect(mockedList.scrollToPosition.mock.calls[0][0]).toEqual(40)
        })
    })

    describe('eventsList', () => {
        it('should load and parse events', async () => {
            await expectLogic(logic, () => {
                sessionRecordingDataLogic.actions.loadRecordingSnapshots('1')
                sessionRecordingDataLogic.actions.loadRecordingMeta('1')
            })
                .toDispatchActionsInAnyOrder([
                    sessionRecordingDataLogic.actionTypes.loadRecordingSnapshotsSuccess,
                    sessionRecordingDataLogic.actionTypes.loadRecordingMetaSuccess,
                    sessionRecordingDataLogic.actionTypes.loadEventsSuccess,
                ])
                .toMatchValues({
                    listEvents: [
                        expect.objectContaining({
                            playerPosition: {
                                time: 0,
                                windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f',
                            },
                            timestamp: '2021-12-09T19:36:59.223000Z',
                            type: 'events',
                        }),
                        expect.objectContaining({
                            playerPosition: {
                                time: 39000,
                                windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f',
                            },
                            timestamp: '2021-12-09T19:37:39.223000Z',
                            type: 'events',
                        }),
                        expect.objectContaining({
                            playerPosition: {
                                time: 40000,
                                windowId: '17da0b29e21c36-0df8b0cc82d45-1c306851-1fa400-17da0b29e2213f',
                            },
                            timestamp: '2021-12-09T19:37:40.223000Z',
                            type: 'events',
                        }),
                        expect.objectContaining({
                            playerPosition: {
                                time: 99000,
                                windowId: '182830cdf4b28a9-02530f1179ed36-1c525635-384000-182830cdf4c2841',
                            },
                            timestamp: '2021-12-09T19:38:39.223000Z',
                            type: 'events',
                        }),
                        expect.objectContaining({
                            playerPosition: {
                                time: 159000,
                                windowId: '182830cdf4b28a9-02530f1179ed36-1c525635-384000-182830cdf4c2841',
                            },
                            timestamp: '2021-12-09T19:39:39.223000Z',
                            type: 'events',
                        }),
                    ],
                })
        })
        it('should filter events by specified window id', async () => {
            await expectLogic(logic, () => {
                sessionRecordingDataLogic.actions.loadRecordingSnapshots('1')
                sessionRecordingDataLogic.actions.loadRecordingMeta('1')
                sharedListLogic.actions.setWindowIdFilter(
                    '182830cdf4b28a9-02530f1179ed36-1c525635-384000-182830cdf4c2841'
                )
            })
                .toDispatchActionsInAnyOrder([
                    sessionRecordingDataLogic.actionTypes.loadEventsSuccess,
                    sharedListLogic.actionTypes.setWindowIdFilter,
                ])
                .toMatchValues({
                    listEvents: [
                        expect.objectContaining({
                            playerPosition: {
                                time: 99000,
                                windowId: '182830cdf4b28a9-02530f1179ed36-1c525635-384000-182830cdf4c2841',
                            },
                            timestamp: '2021-12-09T19:38:39.223000Z',
                            type: 'events',
                        }),
                        expect.objectContaining({
                            playerPosition: {
                                time: 159000,
                                windowId: '182830cdf4b28a9-02530f1179ed36-1c525635-384000-182830cdf4c2841',
                            },
                            timestamp: '2021-12-09T19:39:39.223000Z',
                            type: 'events',
                        }),
                    ],
                })
        })
    })
})
