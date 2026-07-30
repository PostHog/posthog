import { expectLogic } from 'kea-test-utils'
import { EventType } from 'posthog-js/rrweb-types'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { playerInspectorLogic } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import { sessionRecordingExperimentContextLogic } from 'scenes/session-recordings/player/player-meta/sessionRecordingExperimentContextLogic'
import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { RecordingSnapshot, SessionRecordingType } from '~/types'

import { blobSourcesFrom, seedLoadedSources, setupSessionRecordingTest } from '../__mocks__/test-setup'

const playerLogicProps = { sessionRecordingId: '1', playerKey: 'playlist' }

const experimentContextResponse = {
    session_id: '1',
    results: [
        {
            experiment_id: 123,
            experiment_name: 'Checkout CTA copy',
            flag_key: 'checkout-cta',
            variant: 'test',
            variants_seen: ['test'],
            multiple_variants: false,
            first_exposure_timestamp: '2023-08-11T12:03:40.000Z',
            experiment_start_date: '2023-08-01T00:00:00Z',
            experiment_end_date: null,
        },
        {
            experiment_id: 456,
            experiment_name: 'Carried over from earlier session',
            flag_key: 'other-flag',
            variant: 'control',
            variants_seen: ['control'],
            multiple_variants: false,
            first_exposure_timestamp: null,
            experiment_start_date: '2023-08-01T00:00:00Z',
            experiment_end_date: null,
        },
    ],
}

describe('playerInspectorLogic', () => {
    let logic: ReturnType<typeof playerInspectorLogic.build>
    let dataLogic: ReturnType<typeof sessionRecordingDataCoordinatorLogic.build>

    beforeEach(() => {
        setupSessionRecordingTest({
            getMocks: {
                '/api/environments/:team_id/session_recordings/1/': {},
                '/api/projects/:team_id/experiments/session_context/': experimentContextResponse,
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
        // featureFlags persist to localStorage across tests, so pin the experiment-context flag
        // off before the first mount — otherwise a prior test leaves it on and the context load
        // kicks off with stale state. The experiment-variant tests below opt in explicitly.
        featureFlagLogic.actions.setFeatureFlags([], {})

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

    describe('matching events', () => {
        const START = new Date('2025-01-01T00:00:00.000Z').valueOf()
        const MATCHING_EVENT_TS = START + 10000
        // Two one-minute blob sources, so a target inside the first one can be left unloaded
        const SOURCES = blobSourcesFrom(START, ['8', '9'])

        const inc = (timestamp: number): RecordingSnapshot =>
            ({ timestamp, type: EventType.IncrementalSnapshot, windowId: 1, data: {} }) as unknown as RecordingSnapshot

        const matchingProps = {
            sessionRecordingId: '1',
            playerKey: 'matching-event',
            skipToFirstMatchingEvent: true,
            matchingEventsMatchType: {
                matchType: 'uuid' as const,
                matchedEvents: [
                    {
                        uuid: 'matching-event',
                        timestamp: new Date(MATCHING_EVENT_TS).toISOString(),
                        session_id: '1',
                        window_id: '1',
                    },
                ],
            },
        }

        const announceRecordingMeta = (): void => {
            dataLogic.actions.loadRecordingMetaSuccess({
                id: '1',
                start_time: new Date(START).toISOString(),
                end_time: new Date(START + 120000).toISOString(),
                recording_duration: 120,
            } as SessionRecordingType)
        }

        it('waits for the recording start before seeking to the first matching event', async () => {
            const playerLogic = sessionRecordingPlayerLogic(matchingProps)
            const matchingLogic = playerInspectorLogic(matchingProps)
            playerLogic.mount()
            matchingLogic.mount()

            await expectLogic(matchingLogic).toDispatchActions(['loadMatchingEventsSuccess'])
            await expectLogic(playerLogic).toNotHaveDispatchedActions(['seekToTime'])

            announceRecordingMeta()

            await expectLogic(playerLogic).toDispatchActions([playerLogic.actionCreators.seekToTime(9000)])

            matchingLogic.unmount()
            playerLogic.unmount()
        })

        it('does not seek to a matching event that can never be rendered', async () => {
            // everything is loaded and no full snapshot exists anywhere, so no position is renderable
            seedLoadedSources('1', SOURCES, { 0: [inc(START), inc(MATCHING_EVENT_TS)], 1: [inc(START + 61000)] })

            const playerLogic = sessionRecordingPlayerLogic(matchingProps)
            const matchingLogic = playerInspectorLogic(matchingProps)
            playerLogic.mount()
            matchingLogic.mount()

            await expectLogic(matchingLogic).toDispatchActions(['loadMatchingEventsSuccess'])
            announceRecordingMeta()
            await expectLogic(matchingLogic).toDispatchActions(['markSkippedToFirstMatchingEvent'])

            await expectLogic(playerLogic).toNotHaveDispatchedActions(['seekToTime'])
            expect(playerLogic.values.isSkippingToMatchingEvent).toBe(false)

            matchingLogic.unmount()
            playerLogic.unmount()
        })
    })

    describe('experiment variant markers', () => {
        // The featureFlags reducer persists to localStorage, so each test pins the flag state
        // explicitly and remounts the inspector so the context load runs with that state.
        const remountWithFlagState = (enabled: boolean): void => {
            featureFlagLogic.actions.setFeatureFlags(
                enabled ? [FEATURE_FLAGS.REPLAY_EXPERIMENT_CONTEXT] : [],
                enabled ? { [FEATURE_FLAGS.REPLAY_EXPERIMENT_CONTEXT]: true } : {}
            )
            logic.unmount()
            logic = playerInspectorLogic(playerLogicProps)
            logic.mount()
        }

        it('synthesizes one marker per context item with a first-exposure timestamp', async () => {
            remountWithFlagState(true)

            const contextLogic = sessionRecordingExperimentContextLogic({ sessionRecordingId: '1' })
            await expectLogic(contextLogic).toDispatchActions([
                (action) =>
                    action.type === contextLogic.actionTypes.loadExperimentContextSuccess &&
                    action.payload.experimentContext !== null,
            ])

            const markers = logic.values.allItems.items.filter((item) => item.type === 'experiment-variant')
            expect(markers).toHaveLength(1)
            expect(markers[0]).toMatchObject({
                type: 'experiment-variant',
                data: {
                    experimentId: 123,
                    experimentName: 'Checkout CTA copy',
                    flagKey: 'checkout-cta',
                    variant: 'test',
                },
            })

            const seekbarMarkers = logic.values.seekbarItems.filter((item) => item.type === 'experiment-variant')
            expect(seekbarMarkers).toHaveLength(1)
        })

        it('synthesizes no markers when the feature flag is off', async () => {
            remountWithFlagState(false)

            // With the flag off the context load never starts (afterMount is gated on the flag),
            // so there is no exposure data and no markers are synthesized.
            await expectLogic(
                sessionRecordingExperimentContextLogic({ sessionRecordingId: '1' })
            ).toNotHaveDispatchedActions(['loadExperimentContext'])

            expect(logic.values.allItems.items.filter((item) => item.type === 'experiment-variant')).toHaveLength(0)
            expect(logic.values.seekbarItems.filter((item) => item.type === 'experiment-variant')).toHaveLength(0)
        })
    })
})
