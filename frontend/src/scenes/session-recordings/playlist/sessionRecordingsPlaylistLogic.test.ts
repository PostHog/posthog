import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator, RecordingFilters } from '~/types'

import { sessionRecordingDataLogic } from '../player/sessionRecordingDataLogic'
import {
    DEFAULT_RECORDING_FILTERS,
    DEFAULT_SIMPLE_RECORDING_FILTERS,
    defaultRecordingDurationFilter,
    RECORDINGS_LIMIT,
    sessionRecordingsPlaylistLogic,
} from './sessionRecordingsPlaylistLogic'

describe('sessionRecordingsPlaylistLogic', () => {
    let logic: ReturnType<typeof sessionRecordingsPlaylistLogic.build>
    const aRecording = { id: 'abc', viewed: false, recording_duration: 10 }
    const listOfSessionRecordings = [aRecording]

    describe('with no recordings to load', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/:team/session_recordings/properties': {
                        results: [],
                    },

                    '/api/projects/:team/session_recordings': { has_next: false, results: [] },
                    '/api/projects/:team/session_recording_playlists/:playlist_id/recordings': {
                        results: [],
                    },
                },
            })
            initKeaTests()
            logic = sessionRecordingsPlaylistLogic({
                key: 'tests',
                updateSearchParams: true,
            })
            logic.mount()
        })
    })

    describe('with recordings to load', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/:team/session_recordings/properties': {
                        results: [
                            { id: 's1', properties: { blah: 'blah1' } },
                            { id: 's2', properties: { blah: 'blah2' } },
                        ],
                    },

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
                        } else if (
                            JSON.parse(searchParams.get('session_recording_duration') ?? '{}')['value'] === 600
                        ) {
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
                logic = sessionRecordingsPlaylistLogic({
                    key: 'tests',
                    updateSearchParams: true,
                })
                logic.mount()
            })

            describe('core assumptions', () => {
                it('loads recent recordings after mounting', async () => {
                    await expectLogic(logic)
                        .toDispatchActionsInAnyOrder(['loadSessionRecordingsSuccess'])
                        .toMatchValues({
                            sessionRecordings: listOfSessionRecordings,
                        })
                })
            })

            describe('activeSessionRecording', () => {
                it('starts as null', () => {
                    expectLogic(logic).toMatchValues({ activeSessionRecording: undefined })
                })
                it('is set by setSessionRecordingId', () => {
                    expectLogic(logic, () => logic.actions.setSelectedRecordingId('abc'))
                        .toDispatchActions(['loadSessionRecordingsSuccess'])
                        .toMatchValues({
                            selectedRecordingId: 'abc',
                            activeSessionRecording: listOfSessionRecordings[0],
                        })
                    expect(router.values.searchParams).toHaveProperty('sessionRecordingId', 'abc')
                })

                it('is partial if sessionRecordingId not in list', () => {
                    expectLogic(logic, () => logic.actions.setSelectedRecordingId('not-in-list'))
                        .toDispatchActions(['loadSessionRecordingsSuccess'])
                        .toMatchValues({
                            selectedRecordingId: 'not-in-list',
                            activeSessionRecording: { id: 'not-in-list' },
                        })
                    expect(router.values.searchParams).toHaveProperty('sessionRecordingId', 'not-in-list')
                })

                it('is read from the URL on the session recording page', async () => {
                    router.actions.push('/replay', { sessionRecordingId: 'abc' })
                    expect(router.values.searchParams).toHaveProperty('sessionRecordingId', 'abc')

                    await expectLogic(logic)
                        .toDispatchActionsInAnyOrder(['setSelectedRecordingId', 'loadSessionRecordingsSuccess'])
                        .toMatchValues({
                            selectedRecordingId: 'abc',
                            activeSessionRecording: listOfSessionRecordings[0],
                        })
                })

                it('mounts and loads the recording when a recording is opened', () => {
                    expectLogic(logic, async () => logic.asyncActions.setSelectedRecordingId('abcd'))
                        .toMount(sessionRecordingDataLogic({ sessionRecordingId: 'abcd' }))
                        .toDispatchActions(['loadEntireRecording'])
                })

                it('returns the first session recording if none selected', () => {
                    expectLogic(logic).toDispatchActions(['loadSessionRecordingsSuccess']).toMatchValues({
                        selectedRecordingId: undefined,
                        activeSessionRecording: listOfSessionRecordings[0],
                    })
                    expect(router.values.searchParams).not.toHaveProperty('sessionRecordingId', 'not-in-list')
                })
            })

            describe('entityFilters', () => {
                it('starts with default values', () => {
                    expectLogic(logic).toMatchValues({
                        filters: DEFAULT_RECORDING_FILTERS,
                        simpleFilters: DEFAULT_SIMPLE_RECORDING_FILTERS,
                    })
                })

                it('is set by setAdvancedFilters and loads filtered results and sets the url', async () => {
                    await expectLogic(logic, () => {
                        logic.actions.setAdvancedFilters({
                            events: [{ id: '$autocapture', type: 'events', order: 0, name: '$autocapture' }],
                        })
                    })
                        .toDispatchActions([
                            'setAdvancedFilters',
                            'loadSessionRecordings',
                            'loadSessionRecordingsSuccess',
                        ])
                        .toMatchValues({
                            sessionRecordings: ['List of recordings filtered by events'],
                        })
                    expect(router.values.searchParams.advancedFilters).toHaveProperty('events', [
                        { id: '$autocapture', type: 'events', order: 0, name: '$autocapture' },
                    ])
                })

                it('reads filters from the logic props', async () => {
                    logic = sessionRecordingsPlaylistLogic({
                        key: 'tests-with-props',
                        advancedFilters: {
                            events: [{ id: '$autocapture', type: 'events', order: 0, name: '$autocapture' }],
                        },
                        simpleFilters: {
                            properties: [
                                {
                                    key: '$geoip_country_name',
                                    value: ['Australia'],
                                    operator: PropertyOperator.Exact,
                                    type: PropertyFilterType.Person,
                                },
                            ],
                        },
                    })
                    logic.mount()

                    await expectLogic(logic).toMatchValues({
                        advancedFilters: {
                            events: [{ id: '$autocapture', type: 'events', order: 0, name: '$autocapture' }],
                        },
                        simpleFilters: {
                            properties: [
                                { key: '$geoip_country_name', value: ['Australia'], operator: 'exact', type: 'person' },
                            ],
                        },
                    })
                })
            })

            describe('date range', () => {
                it('is set by setAdvancedFilters and fetches results from server and sets the url', async () => {
                    await expectLogic(logic, () => {
                        logic.actions.setAdvancedFilters({
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
                        .toDispatchActions(['setAdvancedFilters', 'loadSessionRecordingsSuccess'])
                        .toMatchValues({ sessionRecordings: ['Recordings filtered by date'] })

                    expect(router.values.searchParams.advancedFilters).toHaveProperty('date_from', '2021-10-05')
                    expect(router.values.searchParams.advancedFilters).toHaveProperty('date_to', '2021-10-20')
                })
            })
            describe('duration filter', () => {
                it('is set by setAdvancedFilters and fetches results from server and sets the url', async () => {
                    await expectLogic(logic, () => {
                        logic.actions.setAdvancedFilters({
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
                        .toDispatchActions(['setAdvancedFilters', 'loadSessionRecordingsSuccess'])
                        .toMatchValues({ sessionRecordings: ['Recordings filtered by duration'] })

                    expect(router.values.searchParams.advancedFilters).toHaveProperty('session_recording_duration', {
                        type: PropertyFilterType.Recording,
                        key: 'duration',
                        value: 600,
                        operator: PropertyOperator.LessThan,
                    })
                })
            })

            describe('set recording from hash param', () => {
                it('loads the correct recording from the hash params', async () => {
                    router.actions.push('/replay/recent', { sessionRecordingId: 'abc' })

                    logic = sessionRecordingsPlaylistLogic({
                        key: 'hash-recording-tests',
                        updateSearchParams: true,
                    })
                    logic.mount()

                    await expectLogic(logic).toDispatchActions(['loadSessionRecordingsSuccess']).toMatchValues({
                        selectedRecordingId: 'abc',
                    })

                    logic.actions.setSelectedRecordingId('1234')
                })
            })

            describe('sessionRecording.viewed', () => {
                it('changes when setSelectedRecordingId is called', async () => {
                    await expectLogic(logic)
                        .toFinishAllListeners()
                        .toMatchValues({
                            sessionRecordingsResponse: {
                                results: [{ ...aRecording }],
                                has_next: undefined,
                            },
                            sessionRecordings: [
                                {
                                    ...aRecording,
                                },
                            ],
                        })

                    await expectLogic(logic, () => {
                        logic.actions.setSelectedRecordingId('abc')
                    })
                        .toFinishAllListeners()
                        .toMatchValues({
                            sessionRecordingsResponse: {
                                results: [
                                    {
                                        ...aRecording,
                                        // at this point the view hasn't updated this object
                                        viewed: false,
                                    },
                                ],
                            },
                            sessionRecordings: [
                                {
                                    ...aRecording,
                                    viewed: true,
                                },
                            ],
                        })
                })

                it('is set by setAdvancedFilters and loads filtered results', async () => {
                    await expectLogic(logic, () => {
                        logic.actions.setAdvancedFilters({
                            events: [{ id: '$autocapture', type: 'events', order: 0, name: '$autocapture' }],
                        })
                    })
                        .toDispatchActions([
                            'setAdvancedFilters',
                            'loadSessionRecordings',
                            'loadSessionRecordingsSuccess',
                        ])
                        .toMatchValues({
                            sessionRecordings: ['List of recordings filtered by events'],
                        })
                })
            })

            it('reads filters from the URL', async () => {
                router.actions.push('/replay', {
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
                    .toDispatchActions(['setAdvancedFilters'])
                    .toMatchValues({
                        filters: {
                            events: [{ id: '$autocapture', type: 'events', order: 0, name: '$autocapture' }],
                            actions: [{ id: '1', type: 'actions', order: 0, name: 'View Recording' }],
                            date_from: '2021-10-01',
                            date_to: '2021-10-10',
                            offset: 50,
                            console_logs: [],
                            console_search_query: '',
                            properties: [],
                            session_recording_duration: {
                                type: PropertyFilterType.Recording,
                                key: 'duration',
                                value: 600,
                                operator: PropertyOperator.LessThan,
                            },
                        },
                    })
            })

            it('reads filters from the URL and defaults the duration filter', async () => {
                router.actions.push('/replay', {
                    advancedFilters: {
                        actions: [{ id: '1', type: 'actions', order: 0, name: 'View Recording' }],
                    },
                })

                await expectLogic(logic)
                    .toDispatchActions(['setAdvancedFilters'])
                    .toMatchValues({
                        advancedFilters: expect.objectContaining({
                            actions: [{ id: '1', type: 'actions', order: 0, name: 'View Recording' }],
                        }),
                        filters: {
                            actions: [{ id: '1', type: 'actions', order: 0, name: 'View Recording' }],
                            session_recording_duration: defaultRecordingDurationFilter,
                            console_logs: [],
                            console_search_query: '',
                            date_from: '-7d',
                            date_to: null,
                            events: [],
                            properties: [],
                        },
                    })
            })

            it('reads advanced filters from the URL', async () => {
                router.actions.push('/replay', {
                    advancedFilters: {
                        events: [{ id: '$autocapture', type: 'events', order: 0, name: '$autocapture' }],
                    },
                })

                await expectLogic(logic)
                    .toDispatchActions(['setAdvancedFilters'])
                    .toMatchValues({
                        advancedFilters: expect.objectContaining({
                            events: [{ id: '$autocapture', type: 'events', order: 0, name: '$autocapture' }],
                        }),
                    })
            })

            it('reads simple filters from the URL', async () => {
                router.actions.push('/replay', {
                    simpleFilters: {
                        properties: [
                            {
                                key: '$geoip_country_name',
                                value: ['Australia'],
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Person,
                            },
                        ],
                    },
                })

                await expectLogic(logic)
                    .toDispatchActions(['setSimpleFilters'])
                    .toMatchValues({
                        simpleFilters: {
                            events: [],
                            properties: [
                                {
                                    key: '$geoip_country_name',
                                    value: ['Australia'],
                                    operator: PropertyOperator.Exact,
                                    type: PropertyFilterType.Person,
                                },
                            ],
                        },
                    })
            })
        })

        describe('person specific logic', () => {
            beforeEach(() => {
                logic = sessionRecordingsPlaylistLogic({
                    key: 'cool_user_99',
                    personUUID: 'cool_user_99',
                    updateSearchParams: true,
                })
                logic.mount()
            })

            it('loads session recordings for a specific user', async () => {
                await expectLogic(logic)
                    .toDispatchActions(['loadSessionRecordingsSuccess'])
                    .toMatchValues({ sessionRecordings: ["List of specific user's recordings from server"] })
            })

            it('reads sessionRecordingId from the URL on the person page', async () => {
                router.actions.push('/person/123', { sessionRecordingId: 'abc' })
                expect(router.values.searchParams).toHaveProperty('sessionRecordingId', 'abc')

                await expectLogic(logic).toDispatchActions([logic.actionCreators.setSelectedRecordingId('abc')])
            })
        })

        describe('total filters count', () => {
            beforeEach(() => {
                logic = sessionRecordingsPlaylistLogic({
                    key: 'cool_user_99',
                    personUUID: 'cool_user_99',
                    updateSearchParams: true,
                })
                logic.mount()
            })
            it('starts with a count of zero', async () => {
                await expectLogic(logic).toMatchValues({ totalFiltersCount: 0 })
            })

            it('counts console log filters', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setAdvancedFilters({
                        console_logs: ['warn', 'error'],
                    } satisfies Partial<RecordingFilters>)
                }).toMatchValues({ totalFiltersCount: 2 })
            })

            it('counts console log search query', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setAdvancedFilters({
                        console_search_query: 'this is a test',
                    } satisfies Partial<RecordingFilters>)
                }).toMatchValues({ totalFiltersCount: 1 })
            })
        })

        describe('resetting filters', () => {
            beforeEach(() => {
                logic = sessionRecordingsPlaylistLogic({
                    key: 'cool_user_99',
                    personUUID: 'cool_user_99',
                    updateSearchParams: true,
                })
                logic.mount()
            })

            it('resets console log filters', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setAdvancedFilters({
                        console_logs: ['warn', 'error'],
                    } satisfies Partial<RecordingFilters>)
                    logic.actions.resetFilters()
                }).toMatchValues({ totalFiltersCount: 0 })
            })
        })

        describe('pinned playlists', () => {
            it('should not show others if there are pinned recordings', () => {
                logic = sessionRecordingsPlaylistLogic({
                    key: 'tests',
                    updateSearchParams: true,
                    pinnedRecordings: ['1234'],
                })
                logic.mount()

                expectLogic(logic).toMatchValues({ showOtherRecordings: false })
            })

            it('should show others if there are no pinned recordings', () => {
                logic = sessionRecordingsPlaylistLogic({
                    key: 'tests',
                    updateSearchParams: true,
                    pinnedRecordings: [],
                })
                logic.mount()

                expectLogic(logic).toMatchValues({ showOtherRecordings: true })
            })
        })
    })
})
