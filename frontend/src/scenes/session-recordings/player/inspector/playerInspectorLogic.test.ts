import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { playerInspectorLogic } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'
import {
    DEFAULT_RECORDING_FILTERS,
    MatchingEventsMatchType,
} from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import {
    AnyPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    RecordingUniversalFilters,
} from '~/types'

import { setupSessionRecordingTest } from '../__mocks__/test-setup'

const playerLogicProps = { sessionRecordingId: '1', playerKey: 'playlist' }

const filtersWithSingleProperty = (property: AnyPropertyFilter): RecordingUniversalFilters => ({
    ...DEFAULT_RECORDING_FILTERS,
    filter_group: {
        type: FilterLogicalOperator.And,
        values: [{ type: FilterLogicalOperator.And, values: [property] }],
    },
})

describe('playerInspectorLogic', () => {
    let logic: ReturnType<typeof playerInspectorLogic.build>
    let dataLogic: ReturnType<typeof sessionRecordingDataCoordinatorLogic.build>

    beforeEach(() => {
        setupSessionRecordingTest({
            getMocks: {
                '/api/environments/:team_id/session_recordings/1/': {},
                '/api/projects/:team/notebooks/recording_comments': {
                    results: [
                        {
                            timeInRecording: 12,
                            comment: 'The comment',
                            notebookShortId: '12345',
                            notebookTitle: 'The notebook',
                            id: 'abcdefg',
                        },
                    ],
                },
                '/api/projects/:team_id/comments': {
                    results: [
                        {
                            id: '019838f3-1bab-0000-fce8-04be1d6b6fe3',
                            created_by: {
                                id: 1,
                                uuid: '019838c5-64ac-0000-9f43-17f1bf64f508',
                                distinct_id: 'xugZUZjVMSe5Ceo67Y1KX85kiQqB4Gp5OSdC02cjsWl',
                                first_name: 'fasda',
                                last_name: '',
                                email: 'paul@posthog.com',
                                is_email_verified: false,
                                hedgehog_config: null,
                                role_at_organization: 'other',
                            },
                            deleted: false,
                            content: '🥶',
                            version: 0,
                            created_at: '2025-07-23T20:21:53.197354Z',
                            item_id: '019838c8-8f12-7dfa-b651-abf957639b4b',
                            item_context: {
                                is_emoji: true,
                                time_in_recording: '2025-07-23T19:37:25.284Z',
                            },
                            scope: 'recording',
                            source_comment: null,
                        },
                        {
                            id: '019838c9-d3bb-0000-dae0-18031d78ad67',
                            created_by: {
                                id: 1,
                                uuid: '019838c5-64ac-0000-9f43-17f1bf64f508',
                                distinct_id: 'xugZUZjVMSe5Ceo67Y1KX85kiQqB4Gp5OSdC02cjsWl',
                                first_name: 'fasda',
                                last_name: '',
                                email: 'paul@posthog.com',
                                is_email_verified: false,
                                hedgehog_config: null,
                                role_at_organization: 'other',
                            },
                            deleted: false,
                            content: '😏',
                            version: 0,
                            created_at: '2025-07-23T19:36:47.813482Z',
                            item_id: '019838c8-8f12-7dfa-b651-abf957639b4b',
                            item_context: {
                                is_emoji: true,
                                time_in_recording: '2025-07-23T19:35:47.216Z',
                            },
                            scope: 'recording',
                            source_comment: null,
                        },
                    ],
                },
            },
        })
        featureFlagLogic.mount()

        dataLogic = sessionRecordingDataCoordinatorLogic(playerLogicProps)
        dataLogic.mount()

        logic = playerInspectorLogic(playerLogicProps)
        logic.mount()
    })

    describe('item comments', () => {
        it('does not load comments without prompting', async () => {
            await expectLogic(logic).toMatchValues({
                sessionNotebookComments: null,
                sessionComments: [],
            })
        })

        it('reads notebook comments from data logic', async () => {
            await expectLogic(dataLogic, () => {
                dataLogic.actions.maybeLoadRecordingMeta()
            }).toDispatchActions(['loadRecordingNotebookCommentsSuccess'])

            await expectLogic(logic).toMatchValues({
                sessionNotebookComments: [
                    {
                        timeInRecording: 12,
                        comment: 'The comment',
                        notebookShortId: '12345',
                        notebookTitle: 'The notebook',
                        id: 'abcdefg',
                    },
                ],
            })
        })

        it('reads comments from data logic', async () => {
            await expectLogic(dataLogic, () => {
                dataLogic.actions.maybeLoadRecordingMeta()
            }).toDispatchActions(['loadRecordingCommentsSuccess'])

            await expectLogic(logic).toMatchValues({
                sessionComments: [
                    {
                        content: '🥶',
                        created_at: '2025-07-23T20:21:53.197354Z',
                        created_by: {
                            distinct_id: 'xugZUZjVMSe5Ceo67Y1KX85kiQqB4Gp5OSdC02cjsWl',
                            email: 'paul@posthog.com',
                            first_name: 'fasda',
                            hedgehog_config: null,
                            id: 1,
                            is_email_verified: false,
                            last_name: '',
                            role_at_organization: 'other',
                            uuid: '019838c5-64ac-0000-9f43-17f1bf64f508',
                        },
                        deleted: false,
                        id: '019838f3-1bab-0000-fce8-04be1d6b6fe3',
                        item_context: {
                            is_emoji: true,
                            time_in_recording: '2025-07-23T19:37:25.284Z',
                        },
                        item_id: '019838c8-8f12-7dfa-b651-abf957639b4b',
                        scope: 'recording',
                        source_comment: null,
                        version: 0,
                    },
                    {
                        content: '😏',
                        created_at: '2025-07-23T19:36:47.813482Z',
                        created_by: {
                            distinct_id: 'xugZUZjVMSe5Ceo67Y1KX85kiQqB4Gp5OSdC02cjsWl',
                            email: 'paul@posthog.com',
                            first_name: 'fasda',
                            hedgehog_config: null,
                            id: 1,
                            is_email_verified: false,
                            last_name: '',
                            role_at_organization: 'other',
                            uuid: '019838c5-64ac-0000-9f43-17f1bf64f508',
                        },
                        deleted: false,
                        id: '019838c9-d3bb-0000-dae0-18031d78ad67',
                        item_context: {
                            is_emoji: true,
                            time_in_recording: '2025-07-23T19:35:47.216Z',
                        },
                        item_id: '019838c8-8f12-7dfa-b651-abf957639b4b',
                        scope: 'recording',
                        source_comment: null,
                        version: 0,
                    },
                ],
            })
        })
    })

    describe('loadMatchingEvents', () => {
        const matchedEvents = [{ uuid: 'event-1', timestamp: '2025-07-23T19:37:25.284Z' }]
        let getMatchingEventsSpy: jest.SpyInstance

        const buildLogic = (
            matchingEventsMatchType: MatchingEventsMatchType,
            playerKey: string
        ): ReturnType<typeof playerInspectorLogic.build> => {
            const props = { sessionRecordingId: '1', playerKey, matchingEventsMatchType }
            const builtLogic = playerInspectorLogic(props)
            builtLogic.mount()
            return builtLogic
        }

        beforeEach(() => {
            getMatchingEventsSpy = jest
                .spyOn(api.recordings, 'getMatchingEvents')
                .mockResolvedValue({ results: matchedEvents })
        })

        afterEach(() => {
            getMatchingEventsSpy.mockRestore()
        })

        it('skips the request for recording-only filters (e.g. visited_page)', async () => {
            // Backend matching_events rejects these with a 400 — guard mirrors that validation
            const recordingOnlyLogic = buildLogic(
                {
                    matchType: 'backend',
                    filters: filtersWithSingleProperty({
                        type: PropertyFilterType.Recording,
                        key: 'visited_page',
                        value: ['/nakup'],
                        operator: PropertyOperator.IContains,
                    }),
                },
                'recording-only'
            )

            await expectLogic(recordingOnlyLogic, () => {
                recordingOnlyLogic.actions.loadMatchingEvents()
            })
                .toDispatchActions(['loadMatchingEventsSuccess'])
                .toNotHaveDispatchedActions(['loadMatchingEventsFailure'])
                .toMatchValues({ matchingEvents: null })

            expect(getMatchingEventsSpy).not.toHaveBeenCalled()
        })

        it('loads matching events when an event-property filter is present', async () => {
            const eventPropertyLogic = buildLogic(
                {
                    matchType: 'backend',
                    filters: filtersWithSingleProperty({
                        type: PropertyFilterType.Event,
                        key: '$current_url',
                        value: ['/nakup'],
                        operator: PropertyOperator.IContains,
                    }),
                },
                'event-property'
            )

            await expectLogic(eventPropertyLogic, () => {
                eventPropertyLogic.actions.loadMatchingEvents()
            })
                .toDispatchActions(['loadMatchingEventsSuccess'])
                .toMatchValues({ matchingEvents: matchedEvents })

            expect(getMatchingEventsSpy).toHaveBeenCalled()
        })
    })

    describe('setTrackedWindow', () => {
        it('starts with no tracked window', async () => {
            await expectLogic(logic, () => {
                logic.actions.setTrackedWindow(null)
            })
                .toDispatchActions(['setTrackedWindow'])
                .toMatchValues({
                    trackedWindow: null,
                })
        })

        it('can set tracked window', async () => {
            await expectLogic(logic).toMatchValues({
                trackedWindow: null,
            })
            await expectLogic(logic, () => {
                logic.actions.setTrackedWindow(1)
            })
                .toDispatchActions(['setTrackedWindow'])
                .toMatchValues({
                    trackedWindow: 1,
                })
        })
    })
})
