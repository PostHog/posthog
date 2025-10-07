import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { sessionRecordingDataCoordinatorLogic } from '../player/sessionRecordingDataCoordinatorLogic'
import { playlistLogic } from './playlistLogic'
import {
    DEFAULT_RECORDING_FILTERS,
    convertLegacyFiltersToUniversalFilters,
    convertUniversalFiltersToRecordingsQuery,
    sessionRecordingsPlaylistLogic,
} from './sessionRecordingsPlaylistLogic'

describe('sessionRecordingsPlaylistLogic', () => {
    let logic: ReturnType<typeof sessionRecordingsPlaylistLogic.build>
    const aRecording = {
        id: 'abc',
        viewed: false,
        recording_duration: 10,
        start_time: '2023-10-12T16:55:36.404000Z',
        console_error_count: 50,
    }
    const bRecording = {
        id: 'def',
        viewed: false,
        recording_duration: 10,
        start_time: '2023-05-12T16:55:36.404000Z',
        console_error_count: 100,
    }
    const listOfSessionRecordings = [aRecording, bRecording]
    const offsetRecording = {
        id: `recording_offset_by_${listOfSessionRecordings.length}`,
        viewed: false,
        recording_duration: 10,
        start_time: '2023-08-12T16:55:36.404000Z',
        console_error_count: 75,
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/session_recordings/properties': {
                    results: [
                        { id: 's1', properties: { blah: 'blah1' } },
                        { id: 's2', properties: { blah: 'blah2' } },
                    ],
                },

                'api/projects/:team/property_definitions/seen_together': { $pageview: true },

                '/api/environments/:team_id/session_recordings': (req) => {
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
                                results: [offsetRecording],
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
                        (searchParams.get('having_predicates')?.length || 0) > 0 &&
                        JSON.parse(searchParams.get('having_predicates') || '[]')[0]['value'] === 600
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
        featureFlagLogic.mount()
    })

    afterEach(() => {
        localStorage.clear()
    })

    describe('global logic', () => {
        beforeEach(() => {
            logic = sessionRecordingsPlaylistLogic({
                key: 'tests',
                updateSearchParams: true,
            })
            logic.mount()
            playlistLogic.mount()
            playlistLogic.actions.setIsFiltersExpanded(false)
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
                    .toMount(sessionRecordingDataCoordinatorLogic({ sessionRecordingId: 'abcd' }))
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
            afterEach(() => {
                logic.actions.setFilters({ order: 'start_time' })
                logic.actions.loadSessionRecordings()
            })

            it('is set by setOrderBy, loads filtered results and orders the non pinned recordings', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setFilters({ order: 'console_error_count' })
                })
                    .toDispatchActions(['loadSessionRecordings', 'loadSessionRecordingsSuccess'])
                    .toMatchValues({
                        filters: expect.objectContaining({ order: 'console_error_count' }),
                    })

                expect(logic.values.otherRecordings.map((r) => r.console_error_count)).toEqual([100, 50])
            })

            it('adds an offset', async () => {
                await expectLogic(logic, () => {
                    logic.actions.loadSessionRecordings()
                })
                    .toDispatchActions(['loadSessionRecordingsSuccess'])
                    .toMatchValues({
                        sessionRecordings: listOfSessionRecordings,
                    })

                await expectLogic(logic, () => {
                    logic.actions.loadSessionRecordings('older')
                })
                    .toDispatchActions(['loadSessionRecordingsSuccess'])
                    .toMatchValues({
                        // reorganises recordings based on start_time
                        sessionRecordings: [aRecording, offsetRecording, bRecording],
                    })
            })
        })

        describe('entityFilters', () => {
            it('starts with default values', () => {
                expectLogic(logic).toMatchValues({
                    filters: DEFAULT_RECORDING_FILTERS,
                })
            })

            it('is set by setFilters and loads filtered results and sets the url', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setFilters({
                        filter_group: {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    type: FilterLogicalOperator.And,
                                    values: [{ id: '$autocapture', type: 'events', order: 0, name: '$autocapture' }],
                                },
                            ],
                        },
                    })
                })
                    .toDispatchActions(['setFilters', 'loadSessionRecordings', 'loadSessionRecordingsSuccess'])
                    .toMatchValues({
                        sessionRecordings: ['List of recordings filtered by events'],
                    })
                expect(router.values.searchParams.filters).toHaveProperty('filter_group', {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [{ id: '$autocapture', type: 'events', order: 0, name: '$autocapture' }],
                        },
                    ],
                })
            })

            it('reads filters from the logic props', async () => {
                logic = sessionRecordingsPlaylistLogic({
                    key: 'tests-with-props',
                    filters: {
                        duration: [],
                        filter_group: {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    type: FilterLogicalOperator.And,
                                    values: [
                                        { id: '$autocapture', type: 'events', order: 0, name: '$autocapture' },
                                        {
                                            key: '$geoip_country_name',
                                            value: ['Australia'],
                                            operator: PropertyOperator.Exact,
                                            type: PropertyFilterType.Person,
                                        },
                                    ],
                                },
                            ],
                        },
                    },
                })
                logic.mount()

                await expectLogic(logic).toMatchValues({
                    filters: {
                        duration: [],
                        filter_group: {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    type: FilterLogicalOperator.And,
                                    values: [
                                        { id: '$autocapture', type: 'events', order: 0, name: '$autocapture' },
                                        {
                                            key: '$geoip_country_name',
                                            value: ['Australia'],
                                            operator: PropertyOperator.Exact,
                                            type: PropertyFilterType.Person,
                                        },
                                    ],
                                },
                            ],
                        },
                    },
                })
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
                    .toDispatchActions(['setFilters', 'loadSessionRecordingsSuccess'])
                    .toMatchValues({ sessionRecordings: ['Recordings filtered by date'] })

                expect(router.values.searchParams.filters).toHaveProperty('date_from', '2021-10-05')
                expect(router.values.searchParams.filters).toHaveProperty('date_to', '2021-10-20')
            })
        })

        describe('duration filter', () => {
            it('is set by setFilters and fetches results from server and sets the url', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setFilters({
                        duration: [
                            {
                                type: PropertyFilterType.Recording,
                                key: 'duration',
                                value: 600,
                                operator: PropertyOperator.LessThan,
                            },
                        ],
                    })
                })
                    .toMatchValues({
                        filters: expect.objectContaining({
                            duration: [
                                {
                                    key: 'duration',
                                    operator: PropertyOperator.LessThan,
                                    type: PropertyFilterType.Recording,
                                    value: 600,
                                },
                            ],
                        }),
                    })
                    .toDispatchActions(['setFilters', 'loadSessionRecordingsSuccess'])
                    .toMatchValues({ sessionRecordings: ['Recordings filtered by duration'] })

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
                            order: 'start_time',
                            order_direction: 'DESC',
                            has_next: undefined,
                            results: listOfSessionRecordings,
                        },
                        sessionRecordings: listOfSessionRecordings,
                    })

                await expectLogic(logic, () => {
                    logic.actions.setSelectedRecordingId('abc')
                })
                    .toFinishAllListeners()
                    .toMatchValues({
                        sessionRecordingsResponse: {
                            has_next: undefined,
                            order: 'start_time',
                            order_direction: 'DESC',
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

            it('is set by setFilters and loads filtered results', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setFilters({
                        filter_group: {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    type: FilterLogicalOperator.And,
                                    values: [{ id: '$autocapture', type: 'events', order: 0, name: '$autocapture' }],
                                },
                            ],
                        },
                    })
                })
                    .toDispatchActions(['setFilters', 'loadSessionRecordings', 'loadSessionRecordingsSuccess'])
                    .toMatchValues({
                        sessionRecordings: ['List of recordings filtered by events'],
                    })
            })
        })

        it('reads filters from the URL', async () => {
            router.actions.push('/replay', {
                filters: {
                    date_from: '2021-10-01',
                    date_to: '2021-10-10',
                    duration: [{ key: 'duration', operator: 'lt', type: 'recording', value: 600 }],
                    filter_group: {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: FilterLogicalOperator.And,
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

            await expectLogic(logic)
                .toDispatchActions(['setFilters'])
                .toMatchValues({
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
                        order: 'start_time',
                        order_direction: 'DESC',
                    },
                })
        })

        it('reads filters from the URL and defaults the duration filter', async () => {
            router.actions.push('/replay', {
                filters: {
                    filter_group: {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: FilterLogicalOperator.And,
                                values: [{ id: '1', type: 'actions', order: 0, name: 'View Recording' }],
                            },
                        ],
                    },
                },
            })

            await expectLogic(logic)
                .toDispatchActions(['setFilters'])
                .toMatchValues({
                    filters: {
                        date_from: '-3d',
                        date_to: null,
                        duration: [{ key: 'active_seconds', operator: 'gt', type: 'recording', value: 5 }],
                        filter_group: {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    type: FilterLogicalOperator.And,
                                    values: [{ id: '1', name: 'View Recording', order: 0, type: 'actions' }],
                                },
                            ],
                        },
                        filter_test_accounts: false,
                        order: 'start_time',
                        order_direction: 'DESC',
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
                logic.actions.setFilters({
                    filter_group: {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: FilterLogicalOperator.And,
                                values: [
                                    {
                                        type: PropertyFilterType.LogEntry,
                                        key: 'level',
                                        operator: PropertyOperator.IContains,
                                        value: ['warn', 'error'],
                                    },
                                ],
                            },
                        ],
                    },
                })
            }).toMatchValues({ totalFiltersCount: 1 })
        })

        it('counts console log search query', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({
                    filter_group: {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: FilterLogicalOperator.And,
                                values: [
                                    {
                                        type: PropertyFilterType.LogEntry,
                                        key: 'message',
                                        operator: PropertyOperator.Exact,
                                        value: 'this is a test',
                                    },
                                ],
                            },
                        ],
                    },
                })
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
                logic.actions.setFilters({
                    filter_group: {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: FilterLogicalOperator.And,
                                values: [
                                    {
                                        type: PropertyFilterType.LogEntry,
                                        key: 'level',
                                        operator: PropertyOperator.IContains,
                                        value: ['warn', 'error'],
                                    },
                                ],
                            },
                        ],
                    },
                })
                logic.actions.resetFilters()
            }).toMatchValues({ totalFiltersCount: 0 })
        })
    })

    describe('set filters', () => {
        beforeEach(() => {
            logic = sessionRecordingsPlaylistLogic({
                key: 'cool_user_99',
                personUUID: 'cool_user_99',
                updateSearchParams: true,
            })
            logic.mount()
        })

        it('resets date_to when given a relative date_from', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({
                    date_from: '2021-10-01',
                    date_to: '2021-10-10',
                })
                logic.actions.setFilters({
                    date_from: '-7d',
                })
            }).toMatchValues({ filters: expect.objectContaining({ date_from: '-7d', date_to: null }) })
        })
    })

    describe('convertUniversalFiltersToRecordingsQuery', () => {
        it('expands the visited_page filter to a pageview with $current_url property', () => {
            const result = convertUniversalFiltersToRecordingsQuery({
                ...DEFAULT_RECORDING_FILTERS,
                filter_group: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    type: PropertyFilterType.Recording,
                                    key: 'visited_page',
                                    value: ['https://example-url.com'],
                                    operator: PropertyOperator.Exact,
                                },
                            ],
                        },
                    ],
                },
                order: 'console_error_count',
                order_direction: 'DESC',
            })

            expect(result).toEqual({
                actions: [],
                console_log_filters: [],
                date_from: '-3d',
                date_to: null,
                events: [
                    {
                        id: '$pageview',
                        name: '$pageview',
                        properties: [
                            {
                                key: '$current_url',
                                operator: 'exact',
                                type: 'event',
                                value: ['https://example-url.com'],
                            },
                        ],
                        type: 'events',
                    },
                ],
                filter_test_accounts: false,
                having_predicates: [
                    {
                        key: 'active_seconds',
                        operator: 'gt',
                        type: 'recording',
                        value: 5,
                    },
                ],
                kind: 'RecordingsQuery',
                operand: 'AND',
                order: 'console_error_count',
                order_direction: 'DESC',
                properties: [],
            })
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
                        key: 'active_seconds',
                        operator: 'gt',
                        type: 'recording',
                        value: 5,
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
                order: 'start_time',
                order_direction: 'DESC',
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
                                    key: 'level',
                                    operator: 'exact',
                                    type: 'log_entry',
                                    value: ['info', 'warn'],
                                },
                                {
                                    key: 'message',
                                    operator: 'exact',
                                    type: 'log_entry',
                                    value: ['this is a query log'],
                                },
                            ],
                        },
                    ],
                },
                filter_test_accounts: true,
                order: 'start_time',
                order_direction: 'DESC',
            })
        })
    })
})
