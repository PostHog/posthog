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
    convertLegacyFiltersToUniversalFilters,
    convertUniversalFiltersToRecordingsQuery,
    getDefaultFilters,
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

                'api/projects/:team/property_definitions/seen_together': { $pageview: true },

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

            it('keeps the current list when fetching a missing selected recording', async () => {
                await expectLogic(logic).toDispatchActions(['loadSessionRecordingsSuccess']).toMatchValues({
                    sessionRecordings: listOfSessionRecordings,
                })

                // A plain reload (e.g. a filter change) resets the list to start fresh
                logic.actions.loadSessionRecordings()
                expect(logic.values.sessionRecordings).toEqual([])

                await expectLogic(logic).toDispatchActions(['loadSessionRecordingsSuccess']).toMatchValues({
                    sessionRecordings: listOfSessionRecordings,
                })

                // A preserveList reload (selecting a not-yet-loaded recording) must not blank the list,
                // otherwise the playlist flashes empty and scroll snaps back to the top
                logic.actions.loadSessionRecordings(undefined, undefined, true)
                expect(logic.values.sessionRecordings).toEqual(listOfSessionRecordings)
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
