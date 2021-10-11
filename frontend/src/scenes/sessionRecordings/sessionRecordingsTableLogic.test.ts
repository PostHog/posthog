import {
    sessionRecordingsTableLogic,
    SessionRecordingsResponse,
    PersonUUID,
    SessionRecordingId,
    DEFAULT_ENTITY_FILTERS,
} from './sessionRecordingsTableLogic'
import { sessionRecordingsTableLogicType } from './sessionRecordingsTableLogicType'
import { BuiltLogic } from 'kea'
import { mockAPI, defaultAPIMocks } from 'lib/api.mock'
import { expectLogic, initKeaTestLogic } from '~/test/kea-test-utils'
import { router } from 'kea-router'
import { PropertyOperator } from '~/types'
import { RecordingWatchedSource } from 'lib/utils/eventUsageLogic'

jest.mock('lib/api')

describe('sessionRecordingsTableLogic', () => {
    let logic: BuiltLogic<sessionRecordingsTableLogicType<PersonUUID, SessionRecordingId, SessionRecordingsResponse>>

    mockAPI(async (url) => {
        const { pathname, searchParams } = url
        if (pathname === 'api/projects/@current/session_recordings') {
            if (searchParams['events'].length > 0 && searchParams['events'][0]['id'] === '$autocapture') {
                return {
                    results: ['List of recordings filtered by events'],
                }
            } else if (searchParams['person_uuid'] === 'cool_user_99') {
                return {
                    results: ["List of specific user's recordings from server"],
                }
            } else if (searchParams['offset'] === 50) {
                return {
                    results: ['List of recordings offset by 50'],
                }
            } else if (searchParams['date_from'] === '2021-10-05' && searchParams['date_to'] === '2021-10-20') {
                return {
                    results: ['Recordings filtered by date'],
                }
            } else if (searchParams['session_recording_duration']['value'] === 600) {
                return {
                    results: ['Recordings filtered by duration'],
                }
            }
            return {
                results: ['List of recordings from server'],
            }
        }
        return defaultAPIMocks(url)
    })

    describe('global logic', () => {
        initKeaTestLogic({
            logic: sessionRecordingsTableLogic,
            onLogic: (l) => (logic = l),
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
                expect(router.values.searchParams).toHaveProperty('sessionRecordingId', 'abc')

                expectLogic(logic, () => logic.actions.closeSessionPlayer()).toMatchValues({ sessionRecordingId: null })
                expect(router.values.searchParams).not.toHaveProperty('sessionRecordingId')
            })

            it('is read from the URL on the session recording page', async () => {
                router.actions.push('/recordings', { sessionRecordingId: 'recording1212' })
                expect(router.values.searchParams).toHaveProperty('sessionRecordingId', 'recording1212')

                await expectLogic(logic)
                    .toDispatchActions(['openSessionPlayer'])
                    .toMatchValues({ sessionRecordingId: 'recording1212' })
            })
        })

        describe('entityFilters', () => {
            it('starts with default values', () => {
                expectLogic(logic).toMatchValues({ entityFilters: DEFAULT_ENTITY_FILTERS })
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

        describe('limit and offset', () => {
            it('is set by loadNext  and loadPrev and gets the right results', async () => {
                await expectLogic(logic, () => {
                    logic.actions.loadNext()
                })
                    .toMatchValues({ offset: 50 })
                    .toDispatchActions(['loadNext', 'getSessionRecordingsSuccess'])
                    .toMatchValues({ sessionRecordings: ['List of recordings offset by 50'] })

                await expectLogic(logic, () => {
                    logic.actions.loadPrev()
                })
                    .toMatchValues({ offset: 0 })
                    .toDispatchActions(['loadPrev', 'getSessionRecordingsSuccess'])
                    .toMatchValues({ sessionRecordings: ['List of recordings from server'] })
            })
        })

        describe('date range', () => {
            it('is set by setDateRange and fetches results from server', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setDateRange('2021-10-05', '2021-10-20')
                })
                    .toMatchValues({ fromDate: '2021-10-05', toDate: '2021-10-20' })
                    .toDispatchActions(['setDateRange', 'getSessionRecordingsSuccess'])
                    .toMatchValues({ sessionRecordings: ['Recordings filtered by date'] })
            })
        })
        describe('duration filter', () => {
            it('starts filtered by gt 1 min', () => {
                expectLogic(logic).toMatchValues({
                    durationFilter: {
                        type: 'recording',
                        key: 'duration',
                        value: 60,
                        operator: PropertyOperator.GreaterThan,
                    },
                })
            })
            it('is set by setDurationFilter and fetches results from server', async () => {
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
    })
    describe('person specific logic', () => {
        initKeaTestLogic({
            logic: sessionRecordingsTableLogic,
            props: {
                personUUID: 'cool_user_99',
            },
            onLogic: (l) => (logic = l),
        })

        it('loads session recordings for a specific user', async () => {
            await expectLogic(logic)
                .toDispatchActions(['getSessionRecordingsSuccess'])
                .toMatchValues({ sessionRecordings: ["List of specific user's recordings from server"] })
        })

        it('reads sessionRecordingId from the URL on the person page', async () => {
            router.actions.push('/person/123', { sessionRecordingId: 'recording1212' })
            expect(router.values.searchParams).toHaveProperty('sessionRecordingId', 'recording1212')

            await expectLogic(logic)
                .toDispatchActions(['openSessionPlayer'])
                .toMatchValues({ sessionRecordingId: 'recording1212' })
        })
    })
})
