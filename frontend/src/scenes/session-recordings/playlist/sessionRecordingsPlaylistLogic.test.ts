import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, RecordingFilters } from '~/types'

import { sessionRecordingDataLogic } from '../player/sessionRecordingDataLogic'
import {
    convertLegacyFiltersToUniversalFilters,
    DEFAULT_RECORDING_UNIVERSAL_FILTERS,
    defaultRecordingDurationFilter,
    sessionRecordingsPlaylistLogic,
} from './sessionRecordingsPlaylistLogic'

describe('sessionRecordingsPlaylistLogic', () => {
    let logic: ReturnType<typeof sessionRecordingsPlaylistLogic.build>
    const aRecording = { id: 'abc', viewed: false, recording_duration: 10, console_error_count: 50 }
    const bRecording = { id: 'def', viewed: false, recording_duration: 10, console_error_count: 100 }
    const listOfSessionRecordings = [aRecording, bRecording]

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/session_recordings/properties': {
                    results: [
                        { id: 's1', properties: { blah: 'blah1' } },
                        { id: 's2', properties: { blah: 'blah2' } },
                    ],
                },

                'api/projects/:team/property_definitions/seen_together': { $pageview: true },

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
                    } else if (searchParams.get('offset') !== null) {
                        return [
                            200,
                            {
                                results: [`List of recordings offset by ${listOfSessionRecordings.length}`],
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
                await expectLogic(logic).toDispatchActionsInAnyOrder(['loadSessionRecordingsSuccess']).toMatchValues({
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

        describe('ordering', () => {
            it('is set by setOrderBy, loads filtered results and orders the non pinned recordings', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setOrderBy('console_error_count')
                })
                    .toDispatchActions(['setOrderBy', 'loadSessionRecordings', 'loadSessionRecordingsSuccess'])
                    .toMatchValues({
                        orderBy: 'console_error_count',
                    })

                expect(logic.values.otherRecordings.map((r) => r.console_error_count)).toEqual([100, 50])
            })

            it('adds an offset when not using latest ordering', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setOrderBy('console_error_count')
                })
                    .toDispatchActionsInAnyOrder(['loadSessionRecordingsSuccess'])
                    .toMatchValues({
                        sessionRecordings: listOfSessionRecordings,
                    })

                await expectLogic(logic, () => {
                    logic.actions.maybeLoadSessionRecordings('newer')
                })
                    .toDispatchActions(['loadSessionRecordingsSuccess'])
                    .toMatchValues({
                        sessionRecordings: [...listOfSessionRecordings, 'List of recordings offset by 2'],
                    })
            })
        })

        describe('entityFilters', () => {
            it('starts with default values', () => {
                expectLogic(logic).toMatchValues({
                    universalFilters: DEFAULT_RECORDING_UNIVERSAL_FILTERS,
                })
            })

            it('is set by setAdvancedFilters and loads filtered results and sets the url', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setAdvancedFilters({
                        events: [{ id: '$autocapture', type: 'events', order: 0, name: '$autocapture' }],
                    })
                })
                    .toDispatchActions(['setAdvancedFilters', 'loadSessionRecordings', 'loadSessionRecordingsSuccess'])
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
                        legacyFilters: expect.objectContaining({
                            date_from: '2021-10-05',
                            date_to: '2021-10-20',
                        }),
                        filters: expect.objectContaining({
                            date_from: '2021-10-05',
                            date_to: '2021-10-20',
                        }),
                    })
                    .toDispatchActions(['setAdvancedFilters', 'loadSessionRecordingsSuccess'])
                    .toMatchValues({ sessionRecordings: ['Recordings filtered by date'] })

                expect(router.values.searchParams.advancedFilters).toHaveProperty('date_from', '2021-10-05')
                expect(router.values.searchParams.filters).toHaveProperty('date_from', '2021-10-05')
                expect(router.values.searchParams.advancedFilters).toHaveProperty('date_to', '2021-10-20')
                expect(router.values.searchParams.filters).toHaveProperty('date_to', '2021-10-20')
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
                        legacyFilters: expect.objectContaining({
                            session_recording_duration: {
                                type: PropertyFilterType.Recording,
                                key: 'duration',
                                value: 600,
                                operator: PropertyOperator.LessThan,
                            },
                        }),
                        filters: expect.objectContaining({
                            duration: [{ key: 'duration', operator: 'lt', type: 'recording', value: 600 }],
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
                expect(router.values.searchParams.filters).toHaveProperty('duration', [
                    {
                        type: PropertyFilterType.Recording,
                        key: 'duration',
                        value: 600,
                        operator: PropertyOperator.LessThan,
                    },
                ])
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
                            results: listOfSessionRecordings,
                            has_next: undefined,
                        },
                        sessionRecordings: listOfSessionRecordings,
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
                                { ...bRecording, viewed: false },
                            ],
                        },
                        sessionRecordings: [
                            {
                                ...aRecording,
                                viewed: true,
                            },
                            { ...bRecording, viewed: false },
                        ],
                    })
            })

            it('is set by setAdvancedFilters and loads filtered results', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setAdvancedFilters({
                        events: [{ id: '$autocapture', type: 'events', order: 0, name: '$autocapture' }],
                    })
                })
                    .toDispatchActions(['setAdvancedFilters', 'loadSessionRecordings', 'loadSessionRecordingsSuccess'])
                    .toMatchValues({
                        sessionRecordings: ['List of recordings filtered by events'],
                    })
            })
        })

        it('reads filters from the URL', async () => {
            router.actions.push('/replay', {
                advancedFilters: {
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
                    operand: FilterLogicalOperator.And,
                },
            })

            await expectLogic(logic)
                .toDispatchActions(['setAdvancedFilters'])
                .toMatchValues({
                    legacyFilters: {
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
                        snapshot_source: null,
                        operand: FilterLogicalOperator.And,
                    },
                    filters: {
                        date_from: '2021-10-01',
                        date_to: '2021-10-10',
                        duration: [{ key: 'duration', operator: 'lt', type: 'recording', value: 600 }],
                        filter_group: {
                            type: 'AND',
                            values: [
                                {
                                    type: 'AND',
                                    values: [
                                        { id: '$autocapture', name: '$autocapture', order: 0, type: 'events' },
                                        { id: '1', name: 'View Recording', order: 0, type: 'actions' },
                                    ],
                                },
                            ],
                        },
                        filter_test_accounts: false,
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
                    legacyFilters: {
                        actions: [{ id: '1', type: 'actions', order: 0, name: 'View Recording' }],
                        session_recording_duration: defaultRecordingDurationFilter,
                        console_logs: [],
                        console_search_query: '',
                        date_from: '-3d',
                        date_to: null,
                        events: [],
                        properties: [],
                        operand: FilterLogicalOperator.And,
                        snapshot_source: null,
                    },
                    filters: {
                        date_from: '-3d',
                        date_to: null,
                        duration: [{ key: 'duration', operator: 'gt', type: 'recording', value: 1 }],
                        filter_group: {
                            type: 'AND',
                            values: [
                                {
                                    type: 'AND',
                                    values: [{ id: '1', name: 'View Recording', order: 0, type: 'actions' }],
                                },
                            ],
                        },
                        filter_test_accounts: false,
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
            }).toMatchValues({ totalFiltersCount: 1 })
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

    describe('convertLegacyFiltersToUniversalFilters', () => {
        it('should return the defaults if values are missing', () => {
            const result = convertLegacyFiltersToUniversalFilters(undefined, {})
            expect(result).toEqual({
                date_from: '-3d',
                date_to: null,
                duration: [
                    {
                        key: 'duration',
                        operator: 'gt',
                        type: 'recording',
                        value: 1,
                    },
                ],
                filter_group: {
                    type: 'AND',
                    values: [
                        {
                            type: 'AND',
                            values: [],
                        },
                    ],
                },
                filter_test_accounts: false,
            })
        })
        it('should parse even the most complex queries', () => {
            const result = convertLegacyFiltersToUniversalFilters(
                {
                    events: [{ key: 'email', value: ['email@posthog.com'], operator: 'exact', type: 'person' }],
                },
                {
                    date_from: '-7d',
                    events: [{ key: 'email', value: ['test@posthog.com'], operator: 'exact', type: 'person' }],
                    console_logs: ['info', 'warn'],
                    console_search_query: 'this is a query log',
                    filter_test_accounts: true,
                    duration_type_filter: 'active_seconds',
                    session_recording_duration: {
                        type: PropertyFilterType.Recording,
                        key: 'duration',
                        value: 3600,
                        operator: PropertyOperator.GreaterThan,
                    },
                }
            )
            expect(result).toEqual({
                date_from: '-7d',
                date_to: null,
                duration: [
                    {
                        key: 'active_seconds',
                        operator: 'gt',
                        type: 'recording',
                        value: 3600,
                    },
                ],
                filter_group: {
                    type: 'AND',
                    values: [
                        {
                            type: 'AND',
                            values: [
                                { key: 'email', value: ['email@posthog.com'], operator: 'exact', type: 'person' },
                                { key: 'email', value: ['test@posthog.com'], operator: 'exact', type: 'person' },
                                {
                                    key: 'console_log_level',
                                    operator: 'exact',
                                    type: 'recording',
                                    value: ['info', 'warn'],
                                },
                                {
                                    key: 'console_log_query',
                                    operator: 'exact',
                                    type: 'recording',
                                    value: ['this is a query log'],
                                },
                            ],
                        },
                    ],
                },
                filter_test_accounts: true,
            })
        })
    })
})
