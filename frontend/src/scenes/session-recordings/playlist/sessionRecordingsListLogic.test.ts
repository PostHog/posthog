import { sessionRecordingsListLogic, RECORDINGS_LIMIT, DEFAULT_RECORDING_FILTERS } from './sessionRecordingsListLogic'
import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { router } from 'kea-router'
import { PropertyFilterType, PropertyOperator } from '~/types'
import { useMocks } from '~/mocks/jest'
import { sessionRecordingDataLogic } from '../player/sessionRecordingDataLogic'

describe('sessionRecordingsListLogic', () => {
    let logic: ReturnType<typeof sessionRecordingsListLogic.build>
    const listOfSessionRecordings = [{ id: 'abc', viewed: false, recording_duration: 10 }]

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/session_recordings': (req) => {
                    const { searchParams } = req.url
                    if (
                        (searchParams.get('events')?.length || 0) > 0 &&
                        JSON.parse(searchParams.get('events') || '[]')[0]?.['id'] === '$autocapture'
                    ) {
                        return [
                            200,
                            {
                                results: ['List of recordings filtered by events'],
                            },
                        ]
                    } else if (searchParams.get('person_uuid') === 'cool_user_99') {
                        return [
                            200,
                            {
                                results: ["List of specific user's recordings from server"],
                            },
                        ]
                    } else if (searchParams.get('offset') === `${RECORDINGS_LIMIT}`) {
                        return [
                            200,
                            {
                                results: [`List of recordings offset by ${RECORDINGS_LIMIT}`],
                            },
                        ]
                    } else if (
                        searchParams.get('date_from') === '2021-10-05' &&
                        searchParams.get('date_to') === '2021-10-20'
                    ) {
                        return [
                            200,
                            {
                                results: ['Recordings filtered by date'],
                            },
                        ]
                    } else if (JSON.parse(searchParams.get('session_recording_duration') ?? '{}')['value'] === 600) {
                        return [
                            200,
                            {
                                results: ['Recordings filtered by duration'],
                            },
                        ]
                    } else if (searchParams.get('static_recordings')) {
                        return [
                            200,
                            {
                                results: ['Recordings belonging to static playlist'],
                            },
                        ]
                    }
                    return [
                        200,
                        {
                            results: listOfSessionRecordings,
                        },
                    ]
                },
                '/api/projects/:team/session_recording_playlists/:playlist_id/recordings': () => {
                    return [
                        200,
                        {
                            results: ['Pinned recordings'],
                        },
                    ]
                },
            },
        })
        initKeaTests()
    })

    describe('global logic', () => {
        beforeEach(() => {
            logic = sessionRecordingsListLogic({
                key: 'tests',
                playlistShortId: 'playlist-test',
                updateSearchParams: true,
            })
            logic.mount()
        })

        describe('core assumptions', () => {
            it('loads recent recordings and pinned recordings after mounting', async () => {
                await expectLogic(logic)
                    .toDispatchActionsInAnyOrder(['getSessionRecordingsSuccess', 'loadPinnedRecordingsSuccess'])
                    .toMatchValues({
                        sessionRecordings: listOfSessionRecordings,
                        pinnedRecordingsResponse: {
                            results: ['Pinned recordings'],
                        },
                    })
            })
        })

        describe('activeSessionRecording', () => {
            it('starts as null', () => {
                expectLogic(logic).toMatchValues({ activeSessionRecording: undefined })
            })
            it('is set by setSessionRecordingId', async () => {
                expectLogic(logic, () => logic.actions.setSelectedRecordingId('abc'))
                    .toDispatchActions(['getSessionRecordingsSuccess'])
                    .toMatchValues({
                        selectedRecordingId: 'abc',
                        activeSessionRecording: listOfSessionRecordings[0],
                    })
                expect(router.values.hashParams).toHaveProperty('sessionRecordingId', 'abc')
            })

            it('is partial if sessionRecordingId not in list', async () => {
                expectLogic(logic, () => logic.actions.setSelectedRecordingId('not-in-list'))
                    .toDispatchActions(['getSessionRecordingsSuccess'])
                    .toMatchValues({
                        selectedRecordingId: 'not-in-list',
                        activeSessionRecording: { id: 'not-in-list' },
                    })
                expect(router.values.hashParams).toHaveProperty('sessionRecordingId', 'not-in-list')
            })

            it('is read from the URL on the session recording page', async () => {
                router.actions.push('/recordings', {}, { sessionRecordingId: 'abc' })
                expect(router.values.hashParams).toHaveProperty('sessionRecordingId', 'abc')

                await expectLogic(logic)
                    .toDispatchActionsInAnyOrder(['setSelectedRecordingId', 'getSessionRecordingsSuccess'])
                    .toMatchValues({
                        selectedRecordingId: 'abc',
                        activeSessionRecording: listOfSessionRecordings[0],
                    })
            })

            it('mounts and loads the recording when a recording is opened', () => {
                expectLogic(logic, async () => await logic.actions.setSelectedRecordingId('abcd'))
                    .toMount(sessionRecordingDataLogic({ sessionRecordingId: 'abcd' }))
                    .toDispatchActions(['loadEntireRecording'])
            })

            it('returns the first session recording if none selected', () => {
                expectLogic(logic).toDispatchActions(['getSessionRecordingsSuccess']).toMatchValues({
                    selectedRecordingId: undefined,
                    activeSessionRecording: listOfSessionRecordings[0],
                })
                expect(router.values.hashParams).not.toHaveProperty('sessionRecordingId', 'not-in-list')
            })
        })

        describe('entityFilters', () => {
            it('starts with default values', () => {
                expectLogic(logic).toMatchValues({ filters: DEFAULT_RECORDING_FILTERS })
            })

            it('is set by setFilters and loads filtered results and sets the url', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setFilters({
                        events: [{ id: '$autocapture', type: 'events', order: 0, name: '$autocapture' }],
                    })
                })
                    .toDispatchActions(['setFilters', 'getSessionRecordings', 'getSessionRecordingsSuccess'])
                    .toMatchValues({
                        sessionRecordings: ['List of recordings filtered by events'],
                    })
                expect(router.values.searchParams.filters).toHaveProperty('events', [
                    { id: '$autocapture', type: 'events', order: 0, name: '$autocapture' },
                ])
            })
        })

        describe('limit and offset', () => {
            it('is set by loadNext  and loadPrev and gets the right results and sets the url', async () => {
                await expectLogic(logic, () => {
                    logic.actions.loadNext()
                })
                    .toMatchValues({ filters: expect.objectContaining({ offset: RECORDINGS_LIMIT }) })
                    .toDispatchActions(['loadNext', 'getSessionRecordingsSuccess'])
                    .toMatchValues({ sessionRecordings: [`List of recordings offset by ${RECORDINGS_LIMIT}`] })
                expect(router.values.searchParams.filters).toHaveProperty('offset', RECORDINGS_LIMIT)

                await expectLogic(logic, () => {
                    logic.actions.loadPrev()
                })
                    .toMatchValues({ filters: expect.objectContaining({ offset: 0 }) })
                    .toDispatchActions(['loadPrev', 'getSessionRecordingsSuccess'])
                    .toMatchValues({ sessionRecordings: listOfSessionRecordings })
                expect(router.values.searchParams.filters).toHaveProperty('offset', 0)
            })
        })

        describe('date range', () => {
            it('is set by setFilters and fetches results from server and sets the url', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setFilters({
                        date_from: '2021-10-05',
                        date_to: '2021-10-20',
                    })
                })
                    .toMatchValues({
                        filters: expect.objectContaining({
                            date_from: '2021-10-05',
                            date_to: '2021-10-20',
                        }),
                    })
                    .toDispatchActions(['setFilters', 'getSessionRecordingsSuccess'])
                    .toMatchValues({ sessionRecordings: ['Recordings filtered by date'] })

                expect(router.values.searchParams.filters).toHaveProperty('date_from', '2021-10-05')
                expect(router.values.searchParams.filters).toHaveProperty('date_to', '2021-10-20')
            })
        })
        describe('duration filter', () => {
            it('is set by setFilters and fetches results from server and sets the url', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setFilters({
                        session_recording_duration: {
                            type: PropertyFilterType.Recording,
                            key: 'duration',
                            value: 600,
                            operator: PropertyOperator.LessThan,
                        },
                    })
                })
                    .toMatchValues({
                        filters: expect.objectContaining({
                            session_recording_duration: {
                                type: PropertyFilterType.Recording,
                                key: 'duration',
                                value: 600,
                                operator: PropertyOperator.LessThan,
                            },
                        }),
                    })
                    .toDispatchActions(['setFilters', 'getSessionRecordingsSuccess'])
                    .toMatchValues({ sessionRecordings: ['Recordings filtered by duration'] })

                expect(router.values.searchParams.filters).toHaveProperty('session_recording_duration', {
                    type: PropertyFilterType.Recording,
                    key: 'duration',
                    value: 600,
                    operator: PropertyOperator.LessThan,
                })
            })
        })

        describe('fetch pinned recordings', () => {
            beforeEach(() => {
                logic = sessionRecordingsListLogic({
                    key: 'static-tests',
                    playlistShortId: 'static-playlist-test',
                })
                logic.mount()
            })
            it('calls list session recordings for static playlists', async () => {
                await expectLogic(logic)
                    .toDispatchActions(['loadPinnedRecordingsSuccess'])
                    .toMatchValues({
                        pinnedRecordingsResponse: {
                            results: ['Pinned recordings'],
                        },
                    })
            })
        })

        describe('set recording from hash param', () => {
            it('loads the correct recording from the hash params', async () => {
                router.actions.push('/recordings/recent', {}, { sessionRecordingId: 'abc' })

                logic = sessionRecordingsListLogic({
                    key: 'hash-recording-tests',
                })
                logic.mount()

                await expectLogic(logic).toDispatchActions(['getSessionRecordingsSuccess']).toMatchValues({
                    selectedRecordingId: 'abc',
                })

                logic.actions.setSelectedRecordingId('1234')
            })
        })

        describe('sessionRecording.viewed', () => {
            it('changes when setSelectedRecordingId is called', () => {
                expectLogic(logic, () => {
                    logic.actions.getSessionRecordingsSuccess({
                        results: [
                            {
                                id: 'abc',
                                viewed: false,
                                recording_duration: 1,
                                start_time: '',
                                end_time: '',
                            },
                        ],
                        has_next: false,
                    })
                }).toMatchValues({
                    sessionRecordings: [
                        {
                            id: 'abc',
                            viewed: false,
                            recording_duration: 1,
                            start_time: '',
                            end_time: '',
                        },
                    ],
                })

                expectLogic(logic, () => {
                    logic.actions.setSelectedRecordingId('abc')
                }).toMatchValues({
                    sessionRecordings: [
                        {
                            id: 'abc',
                            viewed: true,
                            recording_duration: 1,
                            start_time: '',
                            end_time: '',
                        },
                    ],
                })
            })

            it('is set by setFilters and loads filtered results', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setFilters({
                        events: [{ id: '$autocapture', type: 'events', order: 0, name: '$autocapture' }],
                    })
                })
                    .toDispatchActions(['setFilters', 'getSessionRecordings', 'getSessionRecordingsSuccess'])
                    .toMatchValues({
                        sessionRecordings: ['List of recordings filtered by events'],
                    })
            })
        })

        it('reads filters from the URL', async () => {
            router.actions.push('/recordings', {
                filters: {
                    actions: [{ id: '1', type: 'actions', order: 0, name: 'View Recording' }],
                    events: [{ id: '$autocapture', type: 'events', order: 0, name: '$autocapture' }],
                    date_from: '2021-10-01',
                    date_to: '2021-10-10',
                    offset: 50,
                    session_recording_duration: {
                        type: PropertyFilterType.Recording,
                        key: 'duration',
                        value: 600,
                        operator: PropertyOperator.LessThan,
                    },
                },
            })

            await expectLogic(logic)
                .toDispatchActions(['replaceFilters'])
                .toMatchValues({
                    filters: {
                        events: [{ id: '$autocapture', type: 'events', order: 0, name: '$autocapture' }],
                        actions: [{ id: '1', type: 'actions', order: 0, name: 'View Recording' }],
                        date_from: '2021-10-01',
                        date_to: '2021-10-10',
                        offset: 50,
                        session_recording_duration: {
                            type: PropertyFilterType.Recording,
                            key: 'duration',
                            value: 600,
                            operator: PropertyOperator.LessThan,
                        },
                    },
                })
        })
    })
    describe('person specific logic', () => {
        beforeEach(() => {
            logic = sessionRecordingsListLogic({
                key: 'cool_user_99',
                personUUID: 'cool_user_99',
                updateSearchParams: true,
            })
            logic.mount()
        })

        it('loads session recordings for a specific user', async () => {
            await expectLogic(logic)
                .toDispatchActions(['getSessionRecordingsSuccess'])
                .toMatchValues({ sessionRecordings: ["List of specific user's recordings from server"] })
        })

        it('reads sessionRecordingId from the URL on the person page', async () => {
            router.actions.push('/person/123', {}, { sessionRecordingId: 'abc' })
            expect(router.values.hashParams).toHaveProperty('sessionRecordingId', 'abc')

            await expectLogic(logic).toDispatchActions([logic.actionCreators.setSelectedRecordingId('abc')])
        })
    })
})
