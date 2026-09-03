import { expectLogic } from 'kea-test-utils'
import { HttpResponse } from 'msw'

import { RecordingSnapshot } from '@posthog/replay-shared'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import {
    PlayerInspectorLogicProps,
    playerInspectorLogic,
} from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import { sessionRecordingExperimentContextLogic } from 'scenes/session-recordings/player/player-meta/sessionRecordingExperimentContextLogic'
import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { snapshotDataLogic } from 'scenes/session-recordings/player/snapshotDataLogic'
import { DEFAULT_RECORDING_FILTERS } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { useMocks } from '~/mocks/jest'
import { RRWebRecordingConsoleLogPayload, SessionRecordingType } from '~/types'

import { BLOB_SOURCE_V2, overrideSessionRecordingMocks, setupSessionRecordingTest } from '../__mocks__/test-setup'

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

    describe('custom snapshots', () => {
        const customSnapshot = (timestamp: number, data: Record<string, any>): RecordingSnapshot =>
            ({ type: 5, timestamp, windowId: 1, data }) as unknown as RecordingSnapshot

        it('derives doctor items from tagged custom snapshots and skips untagged ones', () => {
            dataLogic.actions.setProcessedSnapshots([
                customSnapshot(1691755416097, { tag: '$session_options', payload: {} }),
                customSnapshot(1691755417097, { payload: { without: 'a tag' } }),
            ])

            expect(logic.values.processedSnapshotData.doctorEvents.map((item) => item.tag)).toEqual([
                'session options',
                'count of snapshot types by window',
            ])
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
        const matchingProps = (
            playerKey: string,
            options: { matchTimestamp?: string; skipToFirstMatchingEvent?: boolean; autoPlay?: boolean } = {}
        ): PlayerInspectorLogicProps => ({
            sessionRecordingId: '1',
            playerKey,
            skipToFirstMatchingEvent: options.skipToFirstMatchingEvent,
            autoPlay: options.autoPlay,
            matchingEventsMatchType: {
                matchType: 'uuid' as const,
                matchedEvents: [
                    { uuid: 'matching-event', timestamp: options.matchTimestamp ?? '2025-01-01T00:00:10.000Z' },
                ],
            },
        })

        const mountLogics = (
            props: PlayerInspectorLogicProps
        ): {
            playerLogic: ReturnType<typeof sessionRecordingPlayerLogic.build>
            matchingLogic: ReturnType<typeof playerInspectorLogic.build>
        } => {
            const playerLogic = sessionRecordingPlayerLogic(props)
            const matchingLogic = playerInspectorLogic(props)
            playerLogic.mount()
            matchingLogic.mount()
            return { playerLogic, matchingLogic }
        }

        const loadRecordingMeta = (): void => {
            dataLogic.actions.loadRecordingMetaSuccess({
                id: '1',
                start_time: '2025-01-01T00:00:00.000Z',
                end_time: '2025-01-01T00:01:00.000Z',
                recording_duration: 60,
            } as SessionRecordingType)
        }

        it.each([
            ['armed via the skipToFirstMatchingEvent prop', { skipToFirstMatchingEvent: true }],
            ['armed during player initialization', {}],
        ])('seeks to the first matching event once the recording is ready (%s)', async (label, options) => {
            const { playerLogic, matchingLogic } = mountLogics(matchingProps(`skip-${label}`, options))

            await expectLogic(matchingLogic).toDispatchActions(['loadMatchingEventsSuccess'])
            await expectLogic(playerLogic).toNotHaveDispatchedActions(['seekToTime'])

            // Meta initializes the player, which arms the skip flag (no t/timestamp URL param)
            loadRecordingMeta()
            await expectLogic(playerLogic).toDispatchActions([
                'setSkipToFirstMatchingEvent',
                playerLogic.actionCreators.seekToTime(9000),
            ])

            matchingLogic.unmount()
            playerLogic.unmount()
        })

        it('still auto-skips when autoplay has started playback', async () => {
            // Autoplay seeks through the internal seekToTimestamp path; only user-facing seeks
            // (seekToTime, scrubbing) consume the pending skip. If an internal seek ever counted
            // as user intent, the skip would silently stop firing on autoplaying playlists.
            const { playerLogic, matchingLogic } = mountLogics(matchingProps('autoplay', { autoPlay: true }))

            await expectLogic(matchingLogic).toDispatchActions(['loadMatchingEventsSuccess'])
            loadRecordingMeta()

            await expectLogic(playerLogic).toDispatchActions([
                'seekToTimestamp', // autoplay's internal seek
                playerLogic.actionCreators.seekToTime(9000),
            ])

            matchingLogic.unmount()
            playerLogic.unmount()
        })

        it.each([
            [
                'seeked',
                (playerLogic: ReturnType<typeof sessionRecordingPlayerLogic.build>) =>
                    playerLogic.actions.seekToTime(5000),
            ],
            [
                'scrubbed',
                (playerLogic: ReturnType<typeof sessionRecordingPlayerLogic.build>) => playerLogic.actions.startScrub(),
            ],
        ])('does not auto-skip after the user has %s', async (interaction, interact) => {
            // Backend matching events resolve on their own schedule, often seconds into playback —
            // a viewer who has already navigated must not have the playhead yanked when they land
            let releaseMatchingEvents: () => void = () => {}
            const gate = new Promise<void>((resolve) => (releaseMatchingEvents = resolve))
            useMocks({
                get: {
                    '/api/environments/:team_id/session_recordings/matching_events': async () => {
                        await gate
                        return [200, { results: [{ uuid: 'matching-event', timestamp: '2025-01-01T00:00:10.000Z' }] }]
                    },
                },
            })

            const { playerLogic, matchingLogic } = mountLogics({
                sessionRecordingId: '1',
                playerKey: `user-${interaction}`,
                matchingEventsMatchType: { matchType: 'backend' as const, filters: DEFAULT_RECORDING_FILTERS },
            })

            loadRecordingMeta()
            // The player is ready and the skip armed, but matching events are still loading
            await expectLogic(playerLogic).toDispatchActions(['setSkipToFirstMatchingEvent'])
            interact(playerLogic)

            releaseMatchingEvents()
            await expectLogic(matchingLogic).toDispatchActions([
                'loadMatchingEventsSuccess',
                'trySkipToFirstMatchingEvent',
            ])
            await expectLogic(playerLogic).toNotHaveDispatchedActions([playerLogic.actionCreators.seekToTime(9000)])

            matchingLogic.unmount()
            playerLogic.unmount()
        })

        it('does not skip again when matching events reload after the skip has fired', async () => {
            // Playlist filters can change under an open recording without user intent (e.g. an
            // async session-id list resolving into the filters), which reloads matching events —
            // that reload must not re-arm the auto-skip and yank the playhead mid-playback.
            const { playerLogic, matchingLogic } = mountLogics(
                matchingProps('reload-after-skip', { skipToFirstMatchingEvent: true })
            )

            await expectLogic(matchingLogic).toDispatchActions(['loadMatchingEventsSuccess'])
            loadRecordingMeta()
            await expectLogic(playerLogic).toDispatchActions([playerLogic.actionCreators.seekToTime(9000)])

            // What propsChanged dispatches when the playlist filters change under the recording
            matchingLogic.actions.loadMatchingEvents()
            await expectLogic(matchingLogic).toDispatchActions([
                'loadMatchingEventsSuccess',
                'trySkipToFirstMatchingEvent',
            ])
            await expectLogic(playerLogic).toNotHaveDispatchedActions(['seekToTime'])

            matchingLogic.unmount()
            playerLogic.unmount()
        })

        it('does not seek when the earliest match falls after the recording ends', async () => {
            // The matching-events query has slack past the recording window; seeking there would
            // pin the player to its final frame and trigger end-reached.
            const props = matchingProps('match-past-end', {
                matchTimestamp: '2025-01-01T00:02:00.000Z',
                skipToFirstMatchingEvent: true,
            })
            const { playerLogic, matchingLogic } = mountLogics(props)

            await expectLogic(matchingLogic).toDispatchActions(['loadMatchingEventsSuccess'])
            loadRecordingMeta()

            // The deferred arming trigger is the last chance for a seek to fire
            await expectLogic(matchingLogic).toDispatchActions([
                'setSkipToFirstMatchingEvent',
                'trySkipToFirstMatchingEvent',
            ])
            await expectLogic(playerLogic).toNotHaveDispatchedActions(['seekToTime'])

            // The out-of-window verdict is terminal: a filter change reloading matching events
            // with an in-window match must not fire the skip mid-playback
            playerInspectorLogic({
                ...props,
                matchingEventsMatchType: {
                    matchType: 'uuid' as const,
                    matchedEvents: [{ uuid: 'in-window-event', timestamp: '2025-01-01T00:00:10.000Z' }],
                },
            })
            await expectLogic(matchingLogic).toDispatchActions([
                'loadMatchingEventsSuccess',
                'trySkipToFirstMatchingEvent',
            ])
            await expectLogic(playerLogic).toNotHaveDispatchedActions(['seekToTime'])

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

    describe('console log snapshots', () => {
        const consoleSnapshot = (
            timestamp: number,
            payload?: RRWebRecordingConsoleLogPayload
        ): Record<string, any> => ({
            type: 6,
            data: { plugin: 'rrweb/console@1', ...(payload ? { payload } : {}) },
            timestamp,
        })

        it('skips a console log snapshot that has no payload instead of crashing', async () => {
            const snapshotLine = JSON.stringify({
                window_id: 'window-1',
                data: [
                    {
                        type: 4,
                        data: { href: 'http://localhost:3000/', width: 100, height: 100 },
                        timestamp: 1682952380877,
                    },
                    consoleSnapshot(1682952380878),
                    consoleSnapshot(1682952380879, { level: 'log', payload: ['hello'], trace: [] }),
                ],
            })
            overrideSessionRecordingMocks({
                getMocks: {
                    '/api/environments/:team_id/session_recordings/:id/snapshots': ({ request }) =>
                        new URL(request.url).searchParams.get('source')
                            ? new HttpResponse(`${snapshotLine}\n`)
                            : [200, { sources: [BLOB_SOURCE_V2] }],
                },
            })

            dataLogic.actions.loadRecordingMeta()
            dataLogic.actions.loadSnapshots()
            await expectLogic(dataLogic).toDispatchActions([
                snapshotDataLogic(playerLogicProps).actionTypes.loadSnapshotsForSourceSuccess,
            ])

            const consoleItems = logic.values.allItems.items.filter((item) => item.type === 'console')
            expect(consoleItems).toHaveLength(1)
            expect(consoleItems[0]).toMatchObject({ data: { content: 'hello', level: 'log' } })
        })
    })
})
