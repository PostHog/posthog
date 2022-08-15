import {
    sessionRecordingsTableLogic,
    DEFAULT_ENTITY_FILTERS,
    DEFAULT_DURATION_FILTER,
} from './sessionRecordingsTableLogic'
import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { router } from 'kea-router'
import { PropertyOperator } from '~/types'
import { RecordingWatchedSource } from 'lib/utils/eventUsageLogic'
import { useMocks } from '~/mocks/jest'

describe('sessionRecordingsTableLogic', () => {
    let logic: ReturnType<typeof sessionRecordingsTableLogic.build>

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
                    } else if (searchParams.get('offset') === '50') {
                        return [
                            200,
                            {
                                results: ['List of recordings offset by 50'],
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
                    }
                    return [
                        200,
                        {
                            results: ['List of recordings from server'],
                        },
                    ]
                },
            },
        })
        initKeaTests()
    })

    describe('global logic', () => {
        beforeEach(() => {
            logic = sessionRecordingsTableLogic({})
            logic.mount()
        })

        describe('core assumptions', () => {
            it('loads session recordings after mounting', async () => {
                await expectLogic(logic)
                    .toDispatchActions(['getSessionRecordingsSuccess'])
                    .toMatchValues({ sessionRecordings: ['List of recordings from server'] })
            })
        })

        describe('sessionRecordingId', () => {
            it('starts as null', () => {
                expectLogic(logic).toMatchValues({ sessionRecordingId: null })
            })
            it('is set by openSessionPlayer and cleared by closeSessionPlayer', async () => {
                expectLogic(logic, () =>
                    logic.actions.openSessionPlayer('abc', RecordingWatchedSource.RecordingsList)
                ).toMatchValues({
                    sessionRecordingId: 'abc',
                })
                expect(router.values.hashParams).toHaveProperty('sessionRecordingId', 'abc')

                expectLogic(logic, () => logic.actions.closeSessionPlayer()).toMatchValues({ sessionRecordingId: null })
                expect(router.values.hashParams).not.toHaveProperty('sessionRecordingId')
            })

            it('is read from the URL on the session recording page', async () => {
                router.actions.push('/recordings', {}, { sessionRecordingId: 'recording1212' })
                expect(router.values.hashParams).toHaveProperty('sessionRecordingId', 'recording1212')

                await expectLogic(logic)
                    .toDispatchActions(['openSessionPlayer'])
                    .toMatchValues({ sessionRecordingId: 'recording1212' })
            })
        })

        describe('entityFilters', () => {
            it('starts with default values', () => {
                expectLogic(logic).toMatchValues({ entityFilters: DEFAULT_ENTITY_FILTERS })
            })

            it('is set by setEntityFilters and loads filtered results and sets the url', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setEntityFilters({
                        events: [{ id: '$autocapture', type: 'events', order: 0, name: '$autocapture' }],
                    })
                })
                    .toDispatchActions(['setEntityFilters', 'getSessionRecordings', 'getSessionRecordingsSuccess'])
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
                    .toMatchValues({ offset: 50 })
                    .toDispatchActions(['loadNext', 'getSessionRecordingsSuccess'])
                    .toMatchValues({ sessionRecordings: ['List of recordings offset by 50'] })
                expect(router.values.searchParams.filters).toHaveProperty('offset', 50)

                await expectLogic(logic, () => {
                    logic.actions.loadPrev()
                })
                    .toMatchValues({ offset: 0 })
                    .toDispatchActions(['loadPrev', 'getSessionRecordingsSuccess'])
                    .toMatchValues({ sessionRecordings: ['List of recordings from server'] })
                expect(router.values.searchParams.filters).toHaveProperty('offset', 0)
            })
        })

        describe('date range', () => {
            it('is set by setDateRange and fetches results from server and sets the url', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setDateRange('2021-10-05', '2021-10-20')
                })
                    .toMatchValues({ fromDate: '2021-10-05', toDate: '2021-10-20' })
                    .toDispatchActions(['setDateRange', 'getSessionRecordingsSuccess'])
                    .toMatchValues({ sessionRecordings: ['Recordings filtered by date'] })

                expect(router.values.searchParams.filters).toHaveProperty('date_from', '2021-10-05')
                expect(router.values.searchParams.filters).toHaveProperty('date_to', '2021-10-20')
            })
        })
        describe('duration filter', () => {
            it('starts filtered by default filter', () => {
                expectLogic(logic).toMatchValues({
                    durationFilter: DEFAULT_DURATION_FILTER,
                })
            })
            it('is set by setDurationFilter and fetches results from server and sets the url', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setDurationFilter({
                        type: 'recording',
                        key: 'duration',
                        value: 600,
                        operator: PropertyOperator.LessThan,
                    })
                })
                    .toMatchValues({
                        durationFilter: {
                            type: 'recording',
                            key: 'duration',
                            value: 600,
                            operator: PropertyOperator.LessThan,
                        },
                    })
                    .toDispatchActions(['setDurationFilter', 'getSessionRecordingsSuccess'])
                    .toMatchValues({ sessionRecordings: ['Recordings filtered by duration'] })

                expect(router.values.searchParams.filters).toHaveProperty('session_recording_duration', {
                    type: 'recording',
                    key: 'duration',
                    value: 600,
                    operator: PropertyOperator.LessThan,
                })
            })
        })

        describe('sessionRecording.viewed', () => {
            it('changes when openSessionRecording is called', () => {
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
                    logic.actions.openSessionPlayer('abc', RecordingWatchedSource.Direct)
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

            it('is set by setEntityFilters and loads filtered results', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setEntityFilters({
                        events: [{ id: '$autocapture', type: 'events', order: 0, name: '$autocapture' }],
                    })
                })
                    .toDispatchActions(['setEntityFilters', 'getSessionRecordings', 'getSessionRecordingsSuccess'])
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
                        type: 'recording',
                        key: 'duration',
                        value: 600,
                        operator: PropertyOperator.LessThan,
                    },
                },
            })

            await expectLogic(logic)
                .toDispatchActions(['setEntityFilters', 'setDateRange', 'setOffset', 'setDurationFilter'])
                .toMatchValues({
                    entityFilters: {
                        events: [{ id: '$autocapture', type: 'events', order: 0, name: '$autocapture' }],
                        actions: [{ id: '1', type: 'actions', order: 0, name: 'View Recording' }],
                    },
                    fromDate: '2021-10-01',
                    toDate: '2021-10-10',
                    offset: 50,
                    durationFilter: {
                        type: 'recording',
                        key: 'duration',
                        value: 600,
                        operator: PropertyOperator.LessThan,
                    },
                })
        })
    })
    describe('person specific logic', () => {
        beforeEach(() => {
            logic = sessionRecordingsTableLogic({ personUUID: 'cool_user_99' })
            logic.mount()
        })

        it('loads session recordings for a specific user', async () => {
            await expectLogic(logic)
                .toDispatchActions(['getSessionRecordingsSuccess'])
                .toMatchValues({ sessionRecordings: ["List of specific user's recordings from server"] })
        })

        it('reads sessionRecordingId from the URL on the person page', async () => {
            router.actions.push('/person/123', {}, { sessionRecordingId: 'recording1212' })
            expect(router.values.hashParams).toHaveProperty('sessionRecordingId', 'recording1212')

            await expectLogic(logic)
                .toDispatchActions(['openSessionPlayer'])
                .toMatchValues({ sessionRecordingId: 'recording1212' })
        })
    })
})
