import { MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import {
    ActionFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    RecordingUniversalFilters,
    UniversalFiltersGroup,
} from '~/types'

import { deletedRecordingsLogic } from '../deletedRecordingsLogic'
import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { sessionRecordingDataCoordinatorLogic } from '../player/sessionRecordingDataCoordinatorLogic'
import { playlistFiltersLogic } from './playlistFiltersLogic'
import {
    DEFAULT_RECORDING_FILTERS,
    DEFAULT_RECORDING_FILTERS_ORDER_BY,
    asUniversalFilters,
    convertLegacyFiltersToUniversalFilters,
    convertUniversalFiltersToRecordingsQuery,
    getDefaultFilters,
    preferredRecordingsSortStorage,
    sessionRecordingsPlaylistLogic,
} from './sessionRecordingsPlaylistLogic'

describe('sessionRecordingsPlaylistLogic', () => {
    let logic: ReturnType<typeof sessionRecordingsPlaylistLogic.build>
    const aRecording = {
        id: 'abc',
        viewed: false,
        recording_duration: 10,
        start_time: '2023-10-12T16:55:36.404000Z',
        end_time: '2023-10-12T16:55:46.404000Z',
        console_error_count: 50,
        viewers: [],
        snapshot_source: 'web' as const,
    }
    const bRecording = {
        id: 'def',
        viewed: false,
        recording_duration: 10,
        start_time: '2023-05-12T16:55:36.404000Z',
        end_time: '2023-05-12T16:55:46.404000Z',
        console_error_count: 100,
        viewers: [],
        snapshot_source: 'web' as const,
    }
    const listOfSessionRecordings = [aRecording, bRecording]
    const offsetRecording = {
        id: `recording_offset_by_${listOfSessionRecordings.length}`,
        viewed: false,
        recording_duration: 10,
        start_time: '2023-08-12T16:55:36.404000Z',
        end_time: '2023-08-12T16:55:46.404000Z',
        console_error_count: 75,
        viewers: [],
        snapshot_source: 'web' as const,
    }
    const outsideFiltersRecording = {
        id: 'outside-filters-rec',
        viewed: false,
        recording_duration: 10,
        start_time: '2023-01-12T16:55:36.404000Z',
        end_time: '2023-01-12T16:55:46.404000Z',
        console_error_count: 0,
        viewers: [],
        snapshot_source: 'web' as const,
        matches_filters: false,
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

                '/api/projects/:team_id/property_definitions/seen_together': ({ request }) => {
                    const eventNames = new URL(request.url).searchParams.getAll('event_names')
                    return [200, Object.fromEntries(eventNames.map((name) => [name, name === '$pageview']))]
                },

                '/api/environments/:team_id/session_recordings': ({ request }) => {
                    const { searchParams } = new URL(request.url)
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
                    } else if (searchParams.get('session_recording_id') === outsideFiltersRecording.id) {
                        // a recording requested via direct link that doesn't match the filters
                        // is included in results flagged with matches_filters false
                        return [
                            200,
                            {
                                results: [outsideFiltersRecording, ...listOfSessionRecordings],
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
                        JSON.parse(searchParams.get('having_predicates') || '[]')[0]?.['value'] === 600
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
                logicKey: 'tests',
                updateSearchParams: true,
            })
            logic.mount()
            playlistFiltersLogic.mount()
            playlistFiltersLogic.actions.setIsFiltersExpanded(false)
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

        describe('selectedRecordingOutsideFilters', () => {
            it('is false when no recording is selected', async () => {
                await expectLogic(logic).toDispatchActions(['loadSessionRecordingsSuccess']).toMatchValues({
                    selectedRecordingOutsideFilters: false,
                })
            })

            it('is false when the selected recording matches the filters', async () => {
                await expectLogic(logic, () => logic.actions.setSelectedRecordingId('abc'))
                    .toDispatchActions(['loadSessionRecordingsSuccess'])
                    .toMatchValues({
                        selectedRecordingId: 'abc',
                        selectedRecordingOutsideFilters: false,
                    })
            })

            it('is true when the selected recording is flagged as not matching the filters', async () => {
                await expectLogic(logic, () => logic.actions.setSelectedRecordingId(outsideFiltersRecording.id))
                    .toDispatchActions(['loadSessionRecordingsSuccess'])
                    .toMatchValues({
                        selectedRecordingId: outsideFiltersRecording.id,
                        selectedRecordingOutsideFilters: true,
                    })
            })
        })

        describe('nextSessionRecording', () => {
            it('returns undefined when autoplay direction is null (autoplay off)', async () => {
                playerSettingsLogic.mount()
                playerSettingsLogic.actions.setAutoplayDirection(null)

                await expectLogic(logic, () => logic.actions.setSelectedRecordingId('abc'))
                    .toDispatchActions(['loadSessionRecordingsSuccess'])
                    .toMatchValues({
                        activeSessionRecording: listOfSessionRecordings[0],
                        nextSessionRecording: undefined,
                    })
            })

            it('returns next older recording when autoplay direction is older', async () => {
                playerSettingsLogic.mount()
                playerSettingsLogic.actions.setAutoplayDirection('older')

                await expectLogic(logic, () => logic.actions.setSelectedRecordingId('abc'))
                    .toDispatchActions(['loadSessionRecordingsSuccess'])
                    .toMatchValues({
                        activeSessionRecording: listOfSessionRecordings[0],
                        nextSessionRecording: listOfSessionRecordings[1],
                    })
            })

            it('returns next newer recording when autoplay direction is newer', async () => {
                playerSettingsLogic.mount()
                playerSettingsLogic.actions.setAutoplayDirection('newer')

                await expectLogic(logic, () => logic.actions.setSelectedRecordingId('def'))
                    .toDispatchActions(['loadSessionRecordingsSuccess'])
                    .toMatchValues({
                        activeSessionRecording: listOfSessionRecordings[1],
                        nextSessionRecording: listOfSessionRecordings[0],
                    })
            })

            it('returns undefined when at the end of the list (older direction)', async () => {
                playerSettingsLogic.mount()
                playerSettingsLogic.actions.setAutoplayDirection('older')

                await expectLogic(logic, () => logic.actions.setSelectedRecordingId('def'))
                    .toDispatchActions(['loadSessionRecordingsSuccess'])
                    .toMatchValues({
                        activeSessionRecording: listOfSessionRecordings[1],
                        nextSessionRecording: undefined,
                    })
            })

            it('returns undefined when at the start of the list (newer direction)', async () => {
                playerSettingsLogic.mount()
                playerSettingsLogic.actions.setAutoplayDirection('newer')

                await expectLogic(logic, () => logic.actions.setSelectedRecordingId('abc'))
                    .toDispatchActions(['loadSessionRecordingsSuccess'])
                    .toMatchValues({
                        activeSessionRecording: listOfSessionRecordings[0],
                        nextSessionRecording: undefined,
                    })
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
                    logicKey: 'tests-with-props',
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

        describe('unusableEventsInFilter', () => {
            // the "All events" pseudo-entity has no id and matches any event, so it must never be
            // flagged as unusable (the group page pins it, so flagging it breaks every group page)
            const allEventsFilter = {
                name: 'All events',
                type: 'events',
                properties: [{ key: "$group_0 = 'test'", type: PropertyFilterType.HogQL }],
            } as ActionFilter
            const unseenEventFilter = { id: 'backend_event', name: 'backend_event', type: 'events' } as ActionFilter

            it.each<[string, ActionFilter[], string[]]>([
                ['only "All events"', [allEventsFilter], []],
                [
                    '"All events" plus an event without $session_id',
                    [allEventsFilter, unseenEventFilter],
                    ['backend_event'],
                ],
            ])('flags no pseudo-entities when filtering by %s', async (_, eventFilters, expected) => {
                await expectLogic(logic, () => {
                    logic.actions.setFilters({
                        filter_group: {
                            type: FilterLogicalOperator.And,
                            values: [{ type: FilterLogicalOperator.And, values: eventFilters }],
                        },
                    })
                })
                    .toDispatchActions(['loadEventsHaveSessionIdSuccess'])
                    .toMatchValues({
                        unusableEventsInFilter: expected,
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
                    logicKey: 'hash-recording-tests',
                    updateSearchParams: true,
                })
                logic.mount()

                await expectLogic(logic).toDispatchActions(['loadSessionRecordingsSuccess']).toMatchValues({
                    selectedRecordingId: 'abc',
                })
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

        it.each<[string, Partial<RecordingUniversalFilters>]>([
            ['date_from', { date_from: '-30d' }],
            ['filter_test_accounts', { filter_test_accounts: true }],
            [
                'duration',
                {
                    duration: [
                        {
                            type: PropertyFilterType.Recording,
                            key: 'duration',
                            operator: PropertyOperator.LessThan,
                            value: 600,
                        },
                    ],
                },
            ],
        ])('resets stale %s to default when a URL filter omits it', async (_field, staleFilters) => {
            const filterGroup = {
                type: FilterLogicalOperator.And,
                values: [
                    {
                        type: FilterLogicalOperator.And,
                        values: [{ id: '1', type: 'actions', order: 0, name: 'View Recording' }],
                    },
                ],
            }

            // stale persisted state from a prior visit
            await expectLogic(logic, () => {
                logic.actions.setFilters(staleFilters)
            }).toDispatchActions(['setFilters'])

            // "View recordings" navigation carrying only filter_group
            router.actions.push('/replay', { filters: { filter_group: filterGroup } })

            await expectLogic(logic)
                .toDispatchActions(['setFilters'])
                .toMatchValues({
                    filters: { ...getDefaultFilters(), filter_group: filterGroup },
                })
        })

        describe('session_ids filter', () => {
            const emptyFilterGroup = {
                type: FilterLogicalOperator.And,
                values: [{ type: FilterLogicalOperator.And, values: [] }],
            }

            it('reads session_ids from the URL, layers them over defaults and passes them to the query', async () => {
                const listSpy = jest.spyOn(api.recordings, 'list')

                router.actions.push('/replay/home', {
                    filters: {
                        session_ids: ['s1', 's2'],
                        date_from: '-7d',
                        filter_group: emptyFilterGroup,
                        duration: [],
                    },
                })

                await expectLogic(logic)
                    .toDispatchActions(['setFilters', 'loadSessionRecordings', 'loadSessionRecordingsSuccess'])
                    .toMatchValues({
                        filters: expect.objectContaining({
                            session_ids: ['s1', 's2'],
                            date_from: '-7d',
                        }),
                    })

                expect(convertUniversalFiltersToRecordingsQuery(logic.values.filters)).toEqual(
                    expect.objectContaining({ session_ids: ['s1', 's2'] })
                )
                expect(listSpy).toHaveBeenLastCalledWith(
                    expect.objectContaining({ session_ids: ['s1', 's2'], date_from: '-7d' })
                )
            })

            it('clears session_ids via setFilters and reloads the list', async () => {
                router.actions.push('/replay/home', {
                    filters: {
                        session_ids: ['s1', 's2'],
                        date_from: '-7d',
                        filter_group: emptyFilterGroup,
                        duration: [],
                    },
                })
                await expectLogic(logic)
                    .toDispatchActions(['setFilters', 'loadSessionRecordingsSuccess'])
                    .toMatchValues({
                        filters: expect.objectContaining({ session_ids: ['s1', 's2'] }),
                    })

                const listSpy = jest.spyOn(api.recordings, 'list')

                await expectLogic(logic, () => {
                    logic.actions.setFilters({ session_ids: undefined })
                }).toDispatchActions(['setFilters', 'loadSessionRecordings', 'loadSessionRecordingsSuccess'])

                expect(logic.values.filters.session_ids).toBeUndefined()
                expect(listSpy).toHaveBeenLastCalledWith(expect.objectContaining({ session_ids: undefined }))
            })

            it('counts session_ids in totalFiltersCount so the badge and reset button reflect them', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setFilters({ session_ids: ['s1', 's2'] })
                }).toMatchValues({ totalFiltersCount: 1 })

                await expectLogic(logic, () => {
                    logic.actions.setFilters({ session_ids: undefined })
                }).toMatchValues({ totalFiltersCount: 0 })
            })
        })

        describe('deleting recordings', () => {
            it('otherRecordings filters out deleted recording ids', async () => {
                await expectLogic(logic)
                    .toDispatchActions(['loadSessionRecordingsSuccess'])
                    .toMatchValues({ otherRecordings: [aRecording, bRecording] })

                deletedRecordingsLogic.actions.addDeletedRecordings(['abc'])

                await expectLogic(logic).toMatchValues({
                    otherRecordings: [bRecording],
                })
            })

            it('clears selectedRecordingId when the active recording is deleted', async () => {
                await expectLogic(logic, () => logic.actions.setSelectedRecordingId('abc'))
                    .toDispatchActions(['loadSessionRecordingsSuccess'])
                    .toMatchValues({ selectedRecordingId: 'abc' })

                deletedRecordingsLogic.actions.addDeletedRecordings(['abc'])

                await expectLogic(logic).toMatchValues({
                    selectedRecordingId: null,
                })
            })

            it('does not clear selectedRecordingId when a different recording is deleted', async () => {
                await expectLogic(logic, () => logic.actions.setSelectedRecordingId('abc'))
                    .toDispatchActions(['loadSessionRecordingsSuccess'])
                    .toMatchValues({ selectedRecordingId: 'abc' })

                deletedRecordingsLogic.actions.addDeletedRecordings(['def'])

                await expectLogic(logic).toMatchValues({
                    selectedRecordingId: 'abc',
                })
            })

            it('bulk delete marks recordings as deleted after API success', async () => {
                jest.spyOn(api.recordings, 'bulkDeleteRecordings').mockResolvedValue({
                    success: true,
                    deleted_count: 2,
                    total_requested: 2,
                    failed_ids: [],
                })

                await expectLogic(logic)
                    .toDispatchActions(['loadSessionRecordingsSuccess'])
                    .toMatchValues({ otherRecordings: [aRecording, bRecording] })

                logic.actions.setSelectedRecordingsIds(['abc', 'def'])
                logic.actions.setIsDeleteSelectedRecordingsDialogOpen(true)

                await expectLogic(logic, () => logic.actions.handleDeleteSelectedRecordings(undefined))
                    .toDispatchActions(['addDeletedRecordings', 'setSelectedRecordingsIds'])
                    .toMatchValues({
                        otherRecordings: [],
                        selectedRecordingsIds: [],
                    })

                expect(api.recordings.bulkDeleteRecordings).toHaveBeenCalledWith(['abc', 'def'], '-3d')
            })

            it('deleted recordings are excluded from hiddenRecordings count', async () => {
                playerSettingsLogic.mount()

                await expectLogic(logic)
                    .toDispatchActions(['loadSessionRecordingsSuccess'])
                    .toMatchValues({ otherRecordings: [aRecording, bRecording] })

                // turning on hide-viewed refetches from the server, so mark abc viewed afterwards
                playerSettingsLogic.actions.setHideViewedRecordings('current-user')
                await expectLogic(logic).toDispatchActions(['loadSessionRecordingsSuccess'])

                // mark abc as viewed so it becomes "hidden" — selecting then deselecting leaves it viewed
                logic.actions.setSelectedRecordingId('abc')
                await expectLogic(logic).toFinishAllListeners()
                // deselect so selectedRecordingId exclusion doesn't interfere
                logic.actions.setSelectedRecordingId(null)

                // abc is now hidden (viewed but not selected)
                await expectLogic(logic).toMatchValues({
                    hiddenRecordings: [expect.objectContaining({ id: 'abc' })],
                })

                // delete abc — should no longer be in hiddenRecordings
                deletedRecordingsLogic.actions.addDeletedRecordings(['abc'])

                await expectLogic(logic).toMatchValues({
                    hiddenRecordings: [],
                })
            })

            it('sends hide_viewed_recordings to the backend when the player setting is set', async () => {
                playerSettingsLogic.mount()
                const listSpy = jest.spyOn(api.recordings, 'list')

                await expectLogic(logic).toDispatchActions(['loadSessionRecordingsSuccess'])

                playerSettingsLogic.actions.setHideViewedRecordings('current-user')
                await expectLogic(logic).toDispatchActions(['loadSessionRecordings', 'loadSessionRecordingsSuccess'])

                expect(listSpy).toHaveBeenLastCalledWith(
                    expect.objectContaining({ hide_viewed_recordings: 'current-user' })
                )
            })

            it('omits hide_viewed_recordings when the player setting is off', async () => {
                playerSettingsLogic.mount()
                const listSpy = jest.spyOn(api.recordings, 'list')

                logic.actions.loadSessionRecordings()
                await expectLogic(logic).toDispatchActions(['loadSessionRecordingsSuccess'])

                expect(listSpy).toHaveBeenLastCalledWith(expect.objectContaining({ hide_viewed_recordings: undefined }))
            })

            it('bulk delete only marks successfully deleted recordings', async () => {
                jest.spyOn(api.recordings, 'bulkDeleteRecordings').mockResolvedValue({
                    success: true,
                    deleted_count: 1,
                    total_requested: 2,
                    failed_ids: ['def'],
                })

                await expectLogic(logic)
                    .toDispatchActions(['loadSessionRecordingsSuccess'])
                    .toMatchValues({ otherRecordings: [aRecording, bRecording] })

                logic.actions.setSelectedRecordingsIds(['abc', 'def'])

                await expectLogic(logic, () => logic.actions.handleDeleteSelectedRecordings(undefined))
                    .toDispatchActions(['addDeletedRecordings'])
                    .toMatchValues({
                        otherRecordings: [bRecording],
                    })
            })

            it('clears a stale selection when filters change, instead of deleting recordings the user can no longer see', async () => {
                await expectLogic(logic)
                    .toDispatchActions(['loadSessionRecordingsSuccess'])
                    .toMatchValues({ otherRecordings: [aRecording, bRecording] })

                logic.actions.setSelectedRecordingsIds(['abc', 'def'])
                await expectLogic(logic).toMatchValues({ selectedRecordingsIds: ['abc', 'def'] })

                logic.actions.setFilters({ date_from: '-30d' })

                await expectLogic(logic).toMatchValues({ selectedRecordingsIds: [] })
            })

            it('ignores a second delete request while one is already in flight', async () => {
                let resolveDelete: (value: {
                    success: boolean
                    deleted_count: number
                    total_requested: number
                    failed_ids: string[]
                }) => void = () => {}
                jest.spyOn(api.recordings, 'bulkDeleteRecordings').mockReturnValue(
                    new Promise((resolve) => {
                        resolveDelete = resolve
                    })
                )

                await expectLogic(logic)
                    .toDispatchActions(['loadSessionRecordingsSuccess'])
                    .toMatchValues({ otherRecordings: [aRecording, bRecording] })

                logic.actions.setSelectedRecordingsIds(['abc', 'def'])

                logic.actions.handleDeleteSelectedRecordings(undefined)
                logic.actions.handleDeleteSelectedRecordings(undefined)

                resolveDelete({ success: true, deleted_count: 2, total_requested: 2, failed_ids: [] })
                await expectLogic(logic).toDispatchActions(['addDeletedRecordings'])

                expect(api.recordings.bulkDeleteRecordings).toHaveBeenCalledTimes(1)
            })
        })
    })

    describe('onRecordingSelected', () => {
        // Under autoPlay the player also picks recordings with no explicit selection — it shows
        // whatever is at the top of the list, and follows it across reloads. Embedding surfaces
        // count opens off this callback, so those implicit moves must be reported too, exactly
        // once each (the experiment recordings tab under-reported opens without this).
        let onRecordingSelected: jest.Mock

        beforeEach(() => {
            onRecordingSelected = jest.fn()
        })

        afterEach(() => {
            jest.restoreAllMocks()
        })

        it('reports the autoplayed top recording on load, and again only when a reload changes it', async () => {
            logic = sessionRecordingsPlaylistLogic({
                logicKey: 'selection-reporting',
                autoPlay: true,
                onRecordingSelected,
            })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadSessionRecordingsSuccess'])
            expect(onRecordingSelected.mock.calls).toEqual([[aRecording.id]])

            // A reload that keeps the same recording on top doesn't move the player, so it must
            // not be reported as another open.
            const listSpy = jest
                .spyOn(api.recordings, 'list')
                .mockResolvedValueOnce({ results: listOfSessionRecordings, has_next: false } as Awaited<
                    ReturnType<typeof api.recordings.list>
                >)
            logic.actions.loadSessionRecordings()
            await expectLogic(logic).toDispatchActions(['loadSessionRecordingsSuccess'])
            expect(onRecordingSelected.mock.calls).toEqual([[aRecording.id]])

            // A reload that changes the top (the way an embedding surface's filter change does,
            // with nothing explicitly selected) moves the player to the new top recording.
            const newestRecording = {
                ...aRecording,
                id: 'newest',
                start_time: '2023-12-12T16:55:36.404000Z',
                end_time: '2023-12-12T16:55:46.404000Z',
            }
            listSpy.mockResolvedValueOnce({ results: [newestRecording], has_next: false } as Awaited<
                ReturnType<typeof api.recordings.list>
            >)
            logic.actions.loadSessionRecordings()
            await expectLogic(logic).toDispatchActions(['loadSessionRecordingsSuccess'])
            expect(onRecordingSelected.mock.calls).toEqual([[aRecording.id], ['newest']])
        })

        it('skips re-selecting the recording already shown, but reports every move — including back', async () => {
            logic = sessionRecordingsPlaylistLogic({
                logicKey: 'selection-reporting-dedupe',
                autoPlay: true,
                onRecordingSelected,
            })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadSessionRecordingsSuccess'])
            expect(onRecordingSelected.mock.calls).toEqual([[aRecording.id]])

            // Clicking the recording the autoplay fallback is already showing opens nothing new.
            logic.actions.setSelectedRecordingId(aRecording.id)
            expect(onRecordingSelected.mock.calls).toEqual([[aRecording.id]])

            logic.actions.setSelectedRecordingId(bRecording.id)
            logic.actions.setSelectedRecordingId(aRecording.id)
            expect(onRecordingSelected.mock.calls).toEqual([[aRecording.id], [bRecording.id], [aRecording.id]])
        })

        it('re-reports a recording that returns after a reload matched nothing', async () => {
            logic = sessionRecordingsPlaylistLogic({
                logicKey: 'selection-reporting-empty-gap',
                autoPlay: true,
                onRecordingSelected,
            })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadSessionRecordingsSuccess'])
            expect(onRecordingSelected.mock.calls).toEqual([[aRecording.id]])

            // A facet can match nothing: the player unloads into the empty state. When the next
            // reload brings the same recording back, it autoplays afresh — a new open, not a
            // re-select of something still on screen.
            const listSpy = jest
                .spyOn(api.recordings, 'list')
                .mockResolvedValueOnce({ results: [], has_next: false } as Awaited<
                    ReturnType<typeof api.recordings.list>
                >)
            logic.actions.loadSessionRecordings()
            await expectLogic(logic).toDispatchActions(['loadSessionRecordingsSuccess'])
            expect(onRecordingSelected.mock.calls).toEqual([[aRecording.id]])

            listSpy.mockResolvedValueOnce({ results: listOfSessionRecordings, has_next: false } as Awaited<
                ReturnType<typeof api.recordings.list>
            >)
            logic.actions.loadSessionRecordings()
            await expectLogic(logic).toDispatchActions(['loadSessionRecordingsSuccess'])
            expect(onRecordingSelected.mock.calls).toEqual([[aRecording.id], [aRecording.id]])
        })

        it('reports nothing on load without autoPlay — only explicit selection', async () => {
            logic = sessionRecordingsPlaylistLogic({
                logicKey: 'selection-reporting-no-autoplay',
                onRecordingSelected,
            })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadSessionRecordingsSuccess'])
            expect(onRecordingSelected).not.toHaveBeenCalled()

            logic.actions.setSelectedRecordingId(aRecording.id)
            expect(onRecordingSelected.mock.calls).toEqual([[aRecording.id]])
        })
    })

    describe('person specific logic', () => {
        beforeEach(() => {
            logic = sessionRecordingsPlaylistLogic({
                logicKey: 'cool_user_99',
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

            await expectLogic(logic)
                .toDispatchActions([logic.actionCreators.setSelectedRecordingId('abc')])
                .toFinishAllListeners()
        })
    })

    describe('total filters count', () => {
        beforeEach(() => {
            logic = sessionRecordingsPlaylistLogic({
                logicKey: 'cool_user_99',
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

    describe('matchingEventsMatchType', () => {
        it('classifies a bare event-property filter as backend', () => {
            // The shape the experiments server-side-flag exposure fallback produces
            // ($feature/<key> with no event filter). Classifying it as 'none' would silently
            // drop match indicators and skip-to-first-matching-event for those lists.
            logic = sessionRecordingsPlaylistLogic({
                logicKey: 'match-type-tests',
                filters: {
                    ...DEFAULT_RECORDING_FILTERS,
                    filter_group: {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: FilterLogicalOperator.And,
                                values: [
                                    {
                                        key: '$feature/my-flag',
                                        type: PropertyFilterType.Event,
                                        value: ['test'],
                                        operator: PropertyOperator.Exact,
                                    },
                                ],
                            },
                        ],
                    },
                },
            })
            logic.mount()

            expect(logic.values.matchingEventsMatchType.matchType).toBe('backend')
        })

        it('does not classify a bare visited_page filter as backend', () => {
            // visited_page is sent to the backend as a recording-type property (matched against
            // the session's all_urls array), which `matching_events` can't highlight against -
            // it only matches event uuids. Classifying it as 'backend' made the player call an
            // endpoint that 400s on every request with no event/action/event-property filter.
            logic = sessionRecordingsPlaylistLogic({
                logicKey: 'match-type-tests-visited-page',
                filters: {
                    ...DEFAULT_RECORDING_FILTERS,
                    filter_group: {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: FilterLogicalOperator.And,
                                values: [
                                    {
                                        key: 'visited_page',
                                        type: PropertyFilterType.Recording,
                                        value: ['https://example-url.com'],
                                        operator: PropertyOperator.Exact,
                                    },
                                ],
                            },
                        ],
                    },
                },
            })
            logic.mount()

            expect(logic.values.matchingEventsMatchType.matchType).toBe('none')
        })
    })

    describe('resetting filters', () => {
        beforeEach(() => {
            logic = sessionRecordingsPlaylistLogic({
                logicKey: 'cool_user_99',
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

    describe('rehydrating persisted filters', () => {
        const props = { logicKey: 'persist_regression', personUUID: 'persist_regression', updateSearchParams: false }

        it('resets a malformed persisted filters value to defaults on mount', async () => {
            // A first mount writes the persist key. Discover its exact name rather than hardcoding
            // kea-localstorage's prefix/path format.
            const seed = sessionRecordingsPlaylistLogic(props)
            seed.mount()
            const filtersKey = Object.keys(localStorage).find(
                (k) => k.includes('persist_regression') && k.endsWith('.filters')
            )
            expect(typeof filtersKey).toBe('string')
            seed.unmount()

            // Poison the persisted entry, then reset the kea context so the reducer rehydrates from
            // storage on the next build - exactly what a stale localStorage entry does in production.
            localStorage.setItem(filtersKey!, JSON.stringify({ filter_group: 'not-a-group', duration: 'nope' }))
            initKeaTests()
            featureFlagLogic.mount()

            logic = sessionRecordingsPlaylistLogic(props)
            logic.mount()

            expect(logic.values.filters).toEqual(getDefaultFilters('persist_regression'))
        })
    })

    describe('set filters', () => {
        beforeEach(() => {
            logic = sessionRecordingsPlaylistLogic({
                logicKey: 'cool_user_99',
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

    describe('superseding or unmounting an in-flight load', () => {
        afterEach(() => {
            jest.restoreAllMocks()
        })

        it('abandons the load instead of failing on unmounted values reads', async () => {
            let resolveList: (value: unknown) => void = () => {}
            const pendingList = new Promise((resolve) => {
                resolveList = resolve
            })
            const listSpy = jest
                .spyOn(api.recordings, 'list')
                .mockImplementation(() => pendingList as ReturnType<typeof api.recordings.list>)

            const embeddedLogic = sessionRecordingsPlaylistLogic({ logicKey: 'unmount-mid-load' })
            embeddedLogic.mount()

            // afterMount kicks off a load; wait for it to get past the debounce and issue the request
            while (listSpy.mock.calls.length === 0) {
                await new Promise((resolve) => setTimeout(resolve, 25))
            }

            embeddedLogic.unmount()
            resolveList({ results: [], has_next: false })

            await expectLogic(embeddedLogic)
                .toFinishAllListeners()
                .toNotHaveDispatchedActions(['loadSessionRecordingsFailure'])
        })

        it('still reports a superseded fetch, with the filters the request was built from', async () => {
            let resolveList: (value: unknown) => void = () => {}
            const pendingList = new Promise((resolve) => {
                resolveList = resolve
            })
            const listSpy = jest
                .spyOn(api.recordings, 'list')
                .mockImplementationOnce(() => pendingList as ReturnType<typeof api.recordings.list>)
                .mockImplementation(
                    () =>
                        Promise.resolve({ results: [], has_next: false } as unknown) as ReturnType<
                            typeof api.recordings.list
                        >
                )

            const supersededLogic = sessionRecordingsPlaylistLogic({ logicKey: 'superseded-mid-load' })
            supersededLogic.mount()

            // afterMount kicks off a load; wait for it to get past the debounce and issue the request
            while (listSpy.mock.calls.length === 0) {
                await new Promise((resolve) => setTimeout(resolve, 25))
            }

            // supersede the in-flight load, then let its stale response land
            supersededLogic.actions.setFilters({ filter_test_accounts: true })
            resolveList({ results: [], has_next: false })

            await expectLogic(supersededLogic)
                .toDispatchActions([
                    (action) =>
                        action.type === supersededLogic.actionTypes.reportRecordingsListFetched &&
                        action.payload.filters.filter_test_accounts !== true,
                ])
                .toFinishAllListeners()

            supersededLogic.unmount()
        })
    })

    describe('convertUniversalFiltersToRecordingsQuery', () => {
        it('passes the visited_page filter as a recording property', () => {
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
                events: [],
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
                properties: [
                    {
                        key: 'visited_page',
                        operator: 'exact',
                        type: 'recording',
                        value: ['https://example-url.com'],
                    },
                ],
            })
        })

        it('passes through session_ids when provided', () => {
            const result = convertUniversalFiltersToRecordingsQuery({
                ...DEFAULT_RECORDING_FILTERS,
                filter_group: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [],
                        },
                    ],
                },
                session_ids: ['session-1', 'session-2', 'session-3'],
            })

            expect(result).toEqual({
                actions: [],
                console_log_filters: [],
                date_from: '-3d',
                date_to: null,
                events: [],
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
                order: 'start_time',
                order_direction: 'DESC',
                properties: [],
                session_ids: ['session-1', 'session-2', 'session-3'],
            })
        })
    })

    describe('asUniversalFilters', () => {
        // A playlist saved before universal filters stores only `events`. Left unconverted it has no
        // filter_group, so the query converter finds nothing to filter on and the list returns
        // everything while the UI shows no criteria.
        it('carries a legacy saved filter through to the recordings query', () => {
            const legacy = { events: [{ id: '$rageclick', type: 'events', order: 0 }] }

            const query = convertUniversalFiltersToRecordingsQuery(asUniversalFilters(legacy as any)!)

            expect(query.events).toEqual([expect.objectContaining({ id: '$rageclick', type: 'events' })])
        })

        it('leaves filters that are already universal untouched', () => {
            const universal = getDefaultFilters()

            expect(asUniversalFilters(universal)).toBe(universal)
        })

        it('returns undefined when there are no stored filters', () => {
            expect(asUniversalFilters(undefined)).toBeUndefined()
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

    describe('getDefaultFilters', () => {
        beforeEach(() => {
            localStorage.clear()
        })

        it('returns filter_test_accounts as false when localStorage is empty', () => {
            const result = getDefaultFilters()
            expect(result.filter_test_accounts).toBe(false)
        })

        it('returns filter_test_accounts as true when localStorage has default_filter_test_accounts set to true', () => {
            localStorage.setItem('default_filter_test_accounts', 'true')
            const result = getDefaultFilters()
            expect(result.filter_test_accounts).toBe(true)
        })

        it('returns filter_test_accounts as false when localStorage has default_filter_test_accounts set to false', () => {
            localStorage.setItem('default_filter_test_accounts', 'false')
            const result = getDefaultFilters()
            expect(result.filter_test_accounts).toBe(false)
        })

        it('returns date_from as -30d for person recordings', () => {
            const result = getDefaultFilters('person-uuid')
            expect(result.date_from).toBe('-30d')
        })

        it('returns date_from as -3d for non-person recordings', () => {
            const result = getDefaultFilters()
            expect(result.date_from).toBe('-3d')
        })

        it('merges pinnedFilters into the default filter_group', () => {
            const pinnedFilters = {
                type: FilterLogicalOperator.And,
                values: [
                    {
                        type: 'events',
                        name: 'All events',
                        properties: [{ key: "$group_0 = 'abc'", type: 'hogql' }],
                    } as ActionFilter,
                ],
            }
            const result = getDefaultFilters(undefined, pinnedFilters)
            const firstGroup = result.filter_group.values[0] as any
            expect(firstGroup.values).toContainEqual(pinnedFilters.values[0])
        })
    })

    describe('relevance sort experiment', () => {
        afterEach(() => {
            jest.restoreAllMocks()
        })

        const mockFlags = (flags: Record<string, string | boolean>): void => {
            jest.spyOn(posthog, 'getFeatureFlag').mockImplementation((key) => flags[key as string] as any)
        }

        const intentPinnedFilters: UniversalFiltersGroup = {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: 'events',
                    name: 'All events',
                    properties: [{ key: "$group_0 = 'abc'", type: 'hogql' }],
                } as ActionFilter,
            ],
        }

        const cases: [
            string,
            Record<string, string | boolean>,
            string,
            { personUUID?: string; pinnedFilters?: UniversalFiltersGroup },
        ][] = [
            [
                'test arm defaults to relevance',
                { [FEATURE_FLAGS.REPLAY_PLAYLIST_RELEVANCE_SORT_EXPERIMENT]: 'test' },
                'surfacing_score',
                {},
            ],
            [
                'control arm keeps recency',
                { [FEATURE_FLAGS.REPLAY_PLAYLIST_RELEVANCE_SORT_EXPERIMENT]: 'control' },
                DEFAULT_RECORDING_FILTERS_ORDER_BY,
                {},
            ],
            ['not enrolled keeps recency', {}, DEFAULT_RECORDING_FILTERS_ORDER_BY, {}],
            [
                'surfacing-score rollout flag forces relevance',
                { [FEATURE_FLAGS.REPLAY_PLAYLIST_SURFACING_SCORE]: true },
                'surfacing_score',
                {},
            ],
            [
                'test arm on a person page keeps recency',
                { [FEATURE_FLAGS.REPLAY_PLAYLIST_RELEVANCE_SORT_EXPERIMENT]: 'test' },
                DEFAULT_RECORDING_FILTERS_ORDER_BY,
                { personUUID: 'some-person-uuid' },
            ],
            [
                'test arm with pinned filters keeps recency',
                { [FEATURE_FLAGS.REPLAY_PLAYLIST_RELEVANCE_SORT_EXPERIMENT]: 'test' },
                DEFAULT_RECORDING_FILTERS_ORDER_BY,
                { pinnedFilters: intentPinnedFilters },
            ],
            [
                'surfacing-score rollout on a person page keeps recency',
                { [FEATURE_FLAGS.REPLAY_PLAYLIST_SURFACING_SCORE]: true },
                DEFAULT_RECORDING_FILTERS_ORDER_BY,
                { personUUID: 'some-person-uuid' },
            ],
        ]

        it.each(cases)('%s', (_name, flags, expectedOrder, { personUUID, pinnedFilters }) => {
            mockFlags(flags)
            expect(getDefaultFilters(personUUID, pinnedFilters).order).toBe(expectedOrder)
        })

        it.each<[string, Partial<RecordingUniversalFilters>, Record<string, unknown>, string]>([
            ['defaults to recency when the URL omits order', {}, {}, DEFAULT_RECORDING_FILTERS_ORDER_BY],
            [
                'respects an explicit order in the URL filters',
                { order: 'console_error_count' },
                {},
                'console_error_count',
            ],
            // order arriving as its own URL search param beside filters takes a separate code path
            ['respects a standalone order URL param', {}, { order: 'console_error_count' }, 'console_error_count'],
        ])(
            'deep link with pre-applied filters %s for the test arm',
            async (_name, extraFilters, extraSearchParams, expectedOrder) => {
                mockFlags({ [FEATURE_FLAGS.REPLAY_PLAYLIST_RELEVANCE_SORT_EXPERIMENT]: 'test' })
                logic = sessionRecordingsPlaylistLogic({
                    logicKey: 'relevance-deep-link-test',
                    updateSearchParams: true,
                })
                logic.mount()

                // "View recordings" style navigation carrying pre-applied filters
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
                        ...extraFilters,
                    },
                    ...extraSearchParams,
                })

                await expectLogic(logic)
                    .toDispatchActions(['setFilters'])
                    .toMatchValues({
                        filters: expect.objectContaining({ order: expectedOrder }),
                    })
            }
        )

        describe('preferred sort', () => {
            it.each<[string, () => void, string, string]>([
                [
                    'an explicitly chosen sort overrides the relevance default',
                    () => preferredRecordingsSortStorage.set({ order: 'start_time', order_direction: 'DESC' }),
                    DEFAULT_RECORDING_FILTERS_ORDER_BY,
                    'DESC',
                ],
                [
                    'the chosen direction is kept',
                    () => preferredRecordingsSortStorage.set({ order: 'start_time', order_direction: 'ASC' }),
                    DEFAULT_RECORDING_FILTERS_ORDER_BY,
                    'ASC',
                ],
                [
                    'an unparseable stored preference is ignored',
                    () => localStorage.setItem(`${MOCK_TEAM_ID}__replay_list_preferred_sort`, 'not json'),
                    'surfacing_score',
                    'DESC',
                ],
                [
                    'a stored order outside the valid set is ignored',
                    () =>
                        localStorage.setItem(
                            `${MOCK_TEAM_ID}__replay_list_preferred_sort`,
                            JSON.stringify({ order: 'unknown', order_direction: 'DESC' })
                        ),
                    'surfacing_score',
                    'DESC',
                ],
            ])('%s', (_name, setup, expectedOrder, expectedDirection) => {
                mockFlags({ [FEATURE_FLAGS.REPLAY_PLAYLIST_SURFACING_SCORE]: true })
                setup()
                const result = getDefaultFilters()
                expect(result.order).toBe(expectedOrder)
                expect(result.order_direction).toBe(expectedDirection)
            })

            it('keeps recency on person pages regardless of the stored preference', () => {
                mockFlags({ [FEATURE_FLAGS.REPLAY_PLAYLIST_SURFACING_SCORE]: true })
                preferredRecordingsSortStorage.set({ order: 'activity_score', order_direction: 'DESC' })
                expect(getDefaultFilters('some-person-uuid').order).toBe(DEFAULT_RECORDING_FILTERS_ORDER_BY)
            })
        })
    })

    describe('pinnedFilters', () => {
        const groupPinnedFilters = {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: 'events',
                    name: 'All events',
                    properties: [{ key: "$group_0 = 'test-group'", type: 'hogql' }],
                } as ActionFilter,
            ],
        }

        beforeEach(() => {
            logic = sessionRecordingsPlaylistLogic({
                logicKey: 'pinned-filters-test',
                pinnedFilters: groupPinnedFilters,
            })
            logic.mount()
        })

        it('includes pinned filters in initial state', () => {
            const firstGroup = logic.values.filters.filter_group.values[0] as any
            expect(firstGroup.values).toContainEqual(groupPinnedFilters.values[0])
        })

        it('preserves pinned filters after setFilters', async () => {
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
                                        value: ['warn'],
                                    },
                                ],
                            },
                        ],
                    },
                })
            }).toMatchValues({
                filters: expect.objectContaining({
                    filter_group: expect.objectContaining({
                        values: expect.arrayContaining([
                            expect.objectContaining({
                                values: expect.arrayContaining([groupPinnedFilters.values[0]]),
                            }),
                        ]),
                    }),
                }),
            })
        })

        it('preserves pinned filters after resetFilters', async () => {
            await expectLogic(logic, () => {
                logic.actions.resetFilters()
            }).toMatchValues({
                filters: expect.objectContaining({
                    filter_group: expect.objectContaining({
                        values: expect.arrayContaining([
                            expect.objectContaining({
                                values: expect.arrayContaining([groupPinnedFilters.values[0]]),
                            }),
                        ]),
                    }),
                }),
            })
        })

        it('does not count pinned filters in totalFiltersCount', async () => {
            await expectLogic(logic).toMatchValues({ totalFiltersCount: 0 })
        })

        it('merges pinned filters into flat filter groups without duplicating', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({
                    filter_group: {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: PropertyFilterType.Person,
                                key: 'email',
                                operator: PropertyOperator.Exact,
                                value: ['test@example.com'],
                            },
                        ],
                    },
                })
            })

            const filterGroup = logic.values.filters.filter_group
            // Should have exactly one nested group
            expect(filterGroup.values).toHaveLength(1)
            const nestedGroup = filterGroup.values[0] as any
            // Nested group should contain pinned + user filter, not duplicates
            expect(nestedGroup.values).toHaveLength(2)
            expect(nestedGroup.values).toContainEqual(groupPinnedFilters.values[0])
        })

        it('counts user-added filters but not pinned ones', async () => {
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
                                        value: ['error'],
                                    },
                                ],
                            },
                        ],
                    },
                })
            }).toMatchValues({ totalFiltersCount: 1 })
        })
    })
})
