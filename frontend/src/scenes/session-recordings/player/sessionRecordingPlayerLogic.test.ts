import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'
import { EventType, IncrementalSource, eventWithTime } from 'posthog-js/rrweb-types'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'
import * as sessionRecordingDataCoordinatorLogicModule from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'
import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerMode,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { makeLogger } from 'scenes/session-recordings/player/utils/player-logging'
import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { ExporterFormat, RecordingSegment, RecordingSnapshot } from '~/types'

import { deletedRecordingsLogic } from '../deletedRecordingsLogic'
import { sessionRecordingEventUsageLogic } from '../sessionRecordingEventUsageLogic'
import {
    BLOB_SOURCE_V2,
    overrideSessionRecordingMocks,
    recordingMetaJson,
    setupSessionRecordingTest,
} from './__mocks__/test-setup'
import { findNewEvents, findSegmentForTimestamp, stripRrwebScriptShims } from './sessionRecordingPlayerLogic'
import { snapshotDataLogic } from './snapshotDataLogic'
import { deleteRecording as deleteRecordingMock } from './utils/playerUtils'

jest.mock('./snapshot-processing/DecompressionWorkerManager')
jest.mock('./utils/playerUtils', () => ({
    ...jest.requireActual('./utils/playerUtils'),
    deleteRecording: jest.fn().mockResolvedValue(undefined),
}))

const makeEvent = (timestamp: number, type: number = EventType.IncrementalSnapshot): eventWithTime =>
    ({ timestamp, type, data: { source: IncrementalSource.MouseMove } }) as unknown as eventWithTime

describe('findNewEvents', () => {
    it.each([
        {
            description: 'forward-only: new events appended at end',
            all: [100, 200, 300, 400, 500],
            current: [100, 200, 300],
            expected: [400, 500],
        },
        {
            description: 'backward: new events inserted before existing',
            all: [100, 200, 300, 400, 500],
            current: [300, 400, 500],
            expected: [100, 200],
        },
        {
            description: 'mixed: new events at both ends',
            all: [100, 200, 300, 400, 500],
            current: [200, 300, 400],
            expected: [100, 500],
        },
        {
            description: 'equal timestamps: correctly counts duplicates',
            all: [100, 100, 100, 200],
            current: [100, 100],
            expected: [100, 200],
        },
        {
            description: 'no new events',
            all: [100, 200, 300],
            current: [100, 200, 300],
            expected: [],
        },
        {
            description: 'empty current: all events are new',
            all: [100, 200, 300],
            current: [],
            expected: [100, 200, 300],
        },
        {
            description: 'interleaved: new events fill gaps',
            all: [100, 150, 200, 250, 300],
            current: [100, 200, 300],
            expected: [150, 250],
        },
    ])('$description', ({ all, current, expected }) => {
        const allSnapshots = all.map((ts) => makeEvent(ts))
        const currentEvents = current.map((ts) => makeEvent(ts))
        const result = findNewEvents(allSnapshots, currentEvents)
        expect(result.map((e) => e.timestamp)).toEqual(expected)
    })
})

describe('stripRrwebScriptShims', () => {
    const countTag = (html: string, tag: string): number => (html.match(new RegExp(`<${tag}\\b`, 'gi')) || []).length

    it.each([
        { description: 'empty string', input: '' },
        { description: 'no noscript tags', input: '<head></head><body><div>hello</div></body>' },
    ])('passes through unchanged when there is nothing to strip ($description)', ({ input }) => {
        expect(stripRrwebScriptShims(input)).toBe(input)
    })

    it('removes inline-script shims (noscript with SCRIPT_PLACEHOLDER body)', () => {
        const input = '<head></head><body><p>real</p><noscript>SCRIPT_PLACEHOLDER</noscript></body>'
        const output = stripRrwebScriptShims(input)
        expect(output).not.toContain('SCRIPT_PLACEHOLDER')
        expect(output).not.toContain('<noscript')
        expect(output).toContain('<p>real</p>')
    })

    it('removes external-script shims (noscript with src/type/async attrs)', () => {
        const input =
            '<head><noscript type="text/javascript" async="" src="https://cdn.example.com/array.js"></noscript></head><body></body>'
        const output = stripRrwebScriptShims(input)
        expect(output).not.toContain('<noscript')
        expect(output).not.toContain('cdn.example.com/array.js')
    })

    it('removes every noscript when many appear in a row (the reported repro)', () => {
        const input =
            '<head>' +
            '<noscript type="text/javascript" async="" src="https://pcdn.example.com/array.js"></noscript>' +
            '<noscript>SCRIPT_PLACEHOLDER</noscript>' +
            '<noscript>SCRIPT_PLACEHOLDER</noscript>' +
            '</head><body><h1>page</h1></body>'
        const output = stripRrwebScriptShims(input)
        expect(countTag(output, 'noscript')).toBe(0)
        expect(output).not.toContain('SCRIPT_PLACEHOLDER')
        expect(output).toContain('<h1>page</h1>')
    })

    it('preserves surrounding DOM structure (head + body content)', () => {
        const input =
            '<head><title>t</title><noscript>SCRIPT_PLACEHOLDER</noscript></head>' +
            '<body><main><p>kept</p></main></body>'
        const output = stripRrwebScriptShims(input)
        expect(output).toContain('<title>t</title>')
        expect(output).toContain('<main><p>kept</p></main>')
        expect(countTag(output, 'noscript')).toBe(0)
    })
})

describe('findSegmentForTimestamp', () => {
    const makeSegment = (
        overrides: Partial<RecordingSegment> & Pick<RecordingSegment, 'startTimestamp' | 'endTimestamp'>
    ): RecordingSegment => ({
        kind: 'window',
        isActive: true,
        durationMs: overrides.endTimestamp - overrides.startTimestamp,
        windowId: 1,
        ...overrides,
    })

    const segments: RecordingSegment[] = [
        makeSegment({ startTimestamp: 1000, endTimestamp: 2000, windowId: 1 }),
        makeSegment({ kind: 'gap', startTimestamp: 2000, endTimestamp: 3000, windowId: 1, isActive: false }),
        makeSegment({ startTimestamp: 3000, endTimestamp: 5000, windowId: 2 }),
    ]

    it('returns null for undefined timestamp', () => {
        expect(findSegmentForTimestamp(segments, undefined)).toBeNull()
    })

    it('returns null for empty segments', () => {
        expect(findSegmentForTimestamp([], 1500)).toBeNull()
    })

    it('returns the matching segment when timestamp is in range', () => {
        const result = findSegmentForTimestamp(segments, 1500)
        expect(result).toEqual(segments[0])
    })

    it('returns the matching segment at exact start boundary', () => {
        expect(findSegmentForTimestamp(segments, 1000)).toEqual(segments[0])
    })

    it('returns the matching segment at exact end boundary', () => {
        expect(findSegmentForTimestamp(segments, 2000)).toEqual(segments[0])
    })

    it('returns gap segment when timestamp is in a gap', () => {
        const result = findSegmentForTimestamp(segments, 2500)
        expect(result).toEqual(segments[1])
    })

    it('falls back to first segment with windowId when timestamp is before all segments', () => {
        const result = findSegmentForTimestamp(segments, 500)
        expect(result).toEqual(segments[0])
        expect(result?.windowId).toBe(1)
    })

    it('falls back to last segment with windowId when timestamp is after all segments', () => {
        const result = findSegmentForTimestamp(segments, 9999)
        expect(result).toEqual(segments[2])
        expect(result?.windowId).toBe(2)
    })

    it('skips segments without windowId when falling back', () => {
        const segmentsWithLeadingGap: RecordingSegment[] = [
            makeSegment({ kind: 'gap', startTimestamp: 0, endTimestamp: 1000, windowId: undefined, isActive: false }),
            makeSegment({ startTimestamp: 1000, endTimestamp: 2000, windowId: 1 }),
        ]

        const result = findSegmentForTimestamp(segmentsWithLeadingGap, -500)
        expect(result?.windowId).toBe(1)
    })

    it('returns synthetic buffer as last resort when no segment has windowId and timestamp is before', () => {
        const segmentsWithoutWindowId: RecordingSegment[] = [
            makeSegment({ startTimestamp: 1000, endTimestamp: 2000, windowId: undefined }),
        ]

        const result = findSegmentForTimestamp(segmentsWithoutWindowId, 500)
        expect(result?.kind).toBe('buffer')
        expect(result?.windowId).toBe(undefined)
        expect(result?.startTimestamp).toBe(500)
        expect(result?.endTimestamp).toBe(999)
    })

    it('returns synthetic buffer as last resort when no segment has windowId and timestamp is after', () => {
        const segmentsWithoutWindowId: RecordingSegment[] = [
            makeSegment({ startTimestamp: 1000, endTimestamp: 2000, windowId: undefined }),
        ]

        const result = findSegmentForTimestamp(segmentsWithoutWindowId, 3000)
        expect(result?.kind).toBe('buffer')
        expect(result?.windowId).toBe(undefined)
        expect(result?.startTimestamp).toBe(3000)
        expect(result?.endTimestamp).toBe(2001)
    })
})

describe('sessionRecordingPlayerLogic', () => {
    let logic: ReturnType<typeof sessionRecordingPlayerLogic.build>
    const mockWarn = jest.fn()

    beforeEach(() => {
        console.warn = mockWarn
        mockWarn.mockClear()
        setupSessionRecordingTest({
            snapshotSources: [BLOB_SOURCE_V2],
        })
        featureFlagLogic.mount()
        logic = sessionRecordingPlayerLogic({ sessionRecordingId: '2', playerKey: 'test', blobV2PollingDisabled: true })
        logic.mount()
    })

    describe('core assumptions', () => {
        it('mounts other logics', async () => {
            await expectLogic(logic).toMount([
                sessionRecordingEventUsageLogic,
                sessionRecordingDataCoordinatorLogic({ sessionRecordingId: '2' }),
                playerSettingsLogic,
            ])
        })
    })

    describe('currentPlayerTime clamping', () => {
        // Mock recording: start=1682952380877, end=1682952392745, durationMs=11868
        const START = 1682952380877
        const DURATION = 11868

        it.each([
            { description: 'before start', timestamp: START - 1000, expected: 0 },
            { description: 'at start', timestamp: START, expected: 0 },
            { description: 'at midpoint', timestamp: START + 5000, expected: 5000 },
            { description: 'at end', timestamp: START + DURATION, expected: DURATION },
            { description: 'beyond end', timestamp: START + DURATION + 5000, expected: DURATION },
        ])('clamps to [$expected] when $description', async ({ timestamp, expected }) => {
            await expectLogic(logic).toDispatchActions([
                sessionRecordingDataCoordinatorLogic({ sessionRecordingId: '2' }).actionTypes.loadRecordingMetaSuccess,
            ])

            logic.actions.setCurrentTimestamp(timestamp)

            expect(logic.values.currentPlayerTime).toBe(expected)
        })
    })

    describe('loading session core', () => {
        it('loads metadata and snapshots by default', async () => {
            silenceKeaLoadersErrors()

            await expectLogic(logic).toDispatchActionsInAnyOrder([
                sessionRecordingDataCoordinatorLogic({ sessionRecordingId: '2' }).actionTypes.loadRecordingMeta,
                sessionRecordingDataCoordinatorLogic({ sessionRecordingId: '2' }).actionTypes.loadRecordingMetaSuccess,
            ])

            expect(logic.values.sessionPlayerData).toMatchSnapshot()

            await expectLogic(logic).toDispatchActions([
                snapshotDataLogic({ sessionRecordingId: '2' }).actionTypes.loadSnapshotSources,
                snapshotDataLogic({ sessionRecordingId: '2' }).actionTypes.loadSnapshotSourcesSuccess,
            ])
        })

        it('loads metadata and snapshots if autoplay', async () => {
            logic.unmount()
            logic = sessionRecordingPlayerLogic({ sessionRecordingId: '2', playerKey: 'test', autoPlay: true })
            logic.mount()

            silenceKeaLoadersErrors()

            await expectLogic(logic).toDispatchActions([
                sessionRecordingDataCoordinatorLogic({ sessionRecordingId: '2' }).actionTypes.loadRecordingData,
                sessionRecordingDataCoordinatorLogic({ sessionRecordingId: '2' }).actionTypes.loadRecordingMeta,
                sessionRecordingDataCoordinatorLogic({ sessionRecordingId: '2' }).actionTypes.loadRecordingMetaSuccess,
                snapshotDataLogic({ sessionRecordingId: '2' }).actionTypes.loadSnapshotSources,
                logic.actionTypes.setPlay,
                snapshotDataLogic({ sessionRecordingId: '2' }).actionTypes.loadSnapshotSourcesSuccess,
            ])

            expect(logic.values.sessionPlayerData).toMatchSnapshot()

            resumeKeaLoadersErrors()
        })

        it('marks as viewed once playing', async () => {
            logic.unmount()
            logic = sessionRecordingPlayerLogic({ sessionRecordingId: '2', playerKey: 'test', autoPlay: true })
            logic.mount()

            silenceKeaLoadersErrors()

            await expectLogic(logic).toDispatchActions([logic.actionTypes.setPlay, logic.actionTypes.markViewed])

            resumeKeaLoadersErrors()
        })

        it('load snapshot errors and triggers error state', async () => {
            logic.unmount()
            overrideSessionRecordingMocks({
                getMocks: {
                    '/api/environments/:team_id/session_recordings/:id/snapshots': () => [500, { status: 0 }],
                    '/api/projects/:team_id/session_recordings/:id/snapshots': () => [500, { status: 0 }],
                },
            })
            logic = sessionRecordingPlayerLogic({
                sessionRecordingId: '2',
                playerKey: 'test',
                autoPlay: true,
            })

            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.seekToTime(50) // greater than null buffered time
            })
                .toDispatchActions([
                    'seekToTimestamp',
                    snapshotDataLogic({ sessionRecordingId: '2' }).actionTypes.loadSnapshotSourcesFailure,
                ])
                .toFinishAllListeners()
                .toDispatchActions(['setPlayerError'])
                .toNotHaveDispatchedActions(['markViewed'])

            expect(logic.values).toMatchObject({
                sessionPlayerData: {
                    person: recordingMetaJson.person,
                    snapshotsByWindowId: {},
                    bufferedToTime: 0,
                },
                playerError: 'loadSnapshotSourcesFailure',
            })
        })

        it('ensures the cache initialization is reset after the player is unmounted', async () => {
            logic.unmount()
            logic = sessionRecordingPlayerLogic({ sessionRecordingId: '2', playerKey: 'test' })
            logic.mount()

            await expectLogic(logic).toDispatchActions([
                sessionRecordingDataCoordinatorLogic({ sessionRecordingId: '2' }).actionTypes.loadRecordingMetaSuccess,
                'initializePlayerFromStart',
            ])
            expect(logic.cache.hasInitialized).toBeTruthy()

            logic.unmount()
            expect(logic.cache.hasInitialized).toBeFalsy()
        })

        // Seeking past the end of a recording should not leave the player
        // stuck buffering. See #53686, #53893.
        it('handles out-of-range ?t= parameter without getting stuck', async () => {
            logic.unmount()
            router.actions.push('/replay/2', { t: '999' })

            logic = sessionRecordingPlayerLogic({
                sessionRecordingId: '2',
                playerKey: 'test',
                blobV2PollingDisabled: true,
            })
            logic.mount()

            await expectLogic(logic)
                .toDispatchActions([
                    sessionRecordingDataCoordinatorLogic({ sessionRecordingId: '2' }).actionTypes
                        .loadRecordingMetaSuccess,
                    'initializePlayerFromStart',
                ])
                .toFinishAllListeners()

            // The player must have a valid timestamp and not be stuck in
            // an unrecoverable state. endReached may legitimately be true
            // here — updateAnimation detects end-of-recording after the
            // normal BUFFER → load cycle completes. The important thing
            // is the player initialized (didn't get stuck before
            // tryInitReplayer) and isn't permanently buffering.
            const start = logic.values.sessionPlayerData.start?.valueOf() ?? 0
            expect(logic.values.currentTimestamp).toBeGreaterThanOrEqual(start)
            expect(logic.values.isBuffering).toBe(false)
        })
    })

    describe('seek renderability clamping', () => {
        // Mock recording meta: start=1682952380877
        const START = 1682952380877
        const LATE_FS_TS = START + 300000

        // Fresh blob keys ('8'/'9') — re-using the default mocks' key '0' would make
        // setSources silently inherit the entry already loaded from the mocks instead
        // of the snapshots seeded here
        const SOURCE_A = {
            source: 'blob_v2',
            blob_key: '8',
            start_timestamp: new Date(START).toISOString(),
            end_timestamp: new Date(START + 60000).toISOString(),
        }
        const SOURCE_B = {
            source: 'blob_v2',
            blob_key: '9',
            start_timestamp: new Date(START + 60000).toISOString(),
            end_timestamp: new Date(LATE_FS_TS + 60000).toISOString(),
        }

        const makeSnapshot = (timestamp: number, type: EventType): RecordingSnapshot =>
            ({ timestamp, type, windowId: 1, data: {} }) as unknown as RecordingSnapshot

        const inc = (timestamp: number): RecordingSnapshot => makeSnapshot(timestamp, EventType.IncrementalSnapshot)
        const fs = (timestamp: number): RecordingSnapshot => makeSnapshot(timestamp, EventType.FullSnapshot)
        // second-window incremental for the multi-window case
        const w2inc = (timestamp: number): RecordingSnapshot =>
            ({ timestamp, type: EventType.IncrementalSnapshot, windowId: 2, data: {} }) as unknown as RecordingSnapshot

        // Seeds the snapshot store and the coordinator's processed snapshots (which
        // segments derive from) directly, bypassing the network loading machinery.
        // Passing null leaves that source unloaded.
        const seedRecording = (
            firstSourceSnapshots: RecordingSnapshot[] | null,
            secondSourceSnapshots: RecordingSnapshot[]
        ): void => {
            const dataLogic = snapshotDataLogic({ sessionRecordingId: '2' })
            dataLogic.actions.loadSnapshotSourcesSuccess([SOURCE_A, SOURCE_B] as any)
            const store = dataLogic.cache.store
            const processed: RecordingSnapshot[] = []
            if (firstSourceSnapshots) {
                store.markLoaded(0, firstSourceSnapshots)
                processed.push(...firstSourceSnapshots)
            }
            store.markLoaded(1, secondSourceSnapshots)
            processed.push(...secondSourceSnapshots)
            dataLogic.actions.storeUpdated()
            sessionRecordingDataCoordinatorLogic({ sessionRecordingId: '2' }).actions.setProcessedSnapshots(processed)
        }

        beforeEach(async () => {
            await expectLogic(logic)
                .toDispatchActions([snapshotDataLogic({ sessionRecordingId: '2' }).actionTypes.loadSnapshotSources])
                .toFinishAllListeners()
        })

        // assertions below run synchronously after the seek dispatch — kea listeners
        // run synchronously up to their first await, and draining listeners instead
        // would let the animation loop advance the playhead past the asserted value

        it.each([
            {
                description: 'clamps a seek into a dead zone forward to the next full snapshot',
                firstSourceSnapshots: [inc(START), inc(START + 1000)],
                secondSourceSnapshots: [fs(LATE_FS_TS)],
                seekTo: START + 1000,
                expectedTimestamp: LATE_FS_TS,
                expectedError: null,
                expectsClampEvent: true,
            },
            {
                // the seek target lies beyond the first source, so the scheduler enters
                // seek mode — the unplayable verdict must still win over buffering
                description: 'errors when fully loaded and no full snapshot exists anywhere',
                firstSourceSnapshots: [inc(START), inc(START + 1000)],
                secondSourceSnapshots: [inc(START + 61000), inc(START + 62000)],
                seekTo: START + 61500,
                expectedTimestamp: START + 61500,
                expectedError: 'noPlayableFullSnapshot',
                expectsClampEvent: false,
            },
            {
                description: 'does not interfere when a full snapshot exists before the seek position',
                firstSourceSnapshots: [fs(START), inc(START + 1000)],
                secondSourceSnapshots: [inc(LATE_FS_TS)],
                seekTo: START + 1000,
                expectedTimestamp: START + 1000,
                expectedError: null,
                expectsClampEvent: false,
            },
        ])(
            '$description',
            ({
                firstSourceSnapshots,
                secondSourceSnapshots,
                seekTo,
                expectedTimestamp,
                expectedError,
                expectsClampEvent,
            }) => {
                seedRecording(firstSourceSnapshots, secondSourceSnapshots)
                const captureSpy = jest.spyOn(posthog, 'capture')
                captureSpy.mockClear()
                logic.actions.setPause()

                logic.actions.seekToTimestamp(seekTo)

                expect(logic.values.currentTimestamp).toBe(expectedTimestamp)
                expect(logic.values.playerError).toBe(expectedError)
                const clampCalls = captureSpy.mock.calls.filter(
                    ([eventName]) => eventName === 'recording player seek clamped to next full snapshot'
                )
                expect(clampCalls).toHaveLength(expectsClampEvent ? 1 : 0)
                if (expectsClampEvent) {
                    expect(clampCalls[0][1]).toMatchObject({
                        seekTimestamp: seekTo,
                        clampedToTimestamp: expectedTimestamp,
                    })
                }
            }
        )

        it('does not clamp or capture when a null currentTimestamp is forwarded during player init', () => {
            // Some callers (e.g. the setPlayer listener) forward currentTimestamp
            // while it still holds its initial null — that must not be coerced to 0
            // and clamped to the FullSnapshot with telemetry on every player init
            seedRecording([inc(START), inc(START + 1000)], [fs(LATE_FS_TS)])
            const captureSpy = jest.spyOn(posthog, 'capture')
            captureSpy.mockClear()

            logic.actions.seekToTimestamp(null as unknown as number)

            const clampCalls = captureSpy.mock.calls.filter(
                ([eventName]) => eventName === 'recording player seek clamped to next full snapshot'
            )
            expect(clampCalls).toHaveLength(0)
            expect(logic.values.currentTimestamp).not.toBe(LATE_FS_TS)
        })

        it('buffers while earlier data that could contain a full snapshot is still loading', () => {
            // The first source is unloaded — it could still contain the window's
            // FullSnapshot, so a seek into the second source's FullSnapshot-less data
            // must buffer, not clamp
            seedRecording(null, [inc(START + 61000), inc(START + 62000)])

            logic.actions.seekToTimestamp(START + 61500)

            expect(logic.values.isBuffering).toBe(true)
            expect(logic.values.playerError).toBeNull()
            expect(logic.values.currentTimestamp).toBe(START + 61500)
        })

        // Same fully-loaded, no-full-snapshot-anywhere data as the "errors when fully loaded"
        // case above. Both sides of the ingestion grace boundary: while within it the missing
        // FullSnapshot may still arrive, so the seek buffers (and keeps loading sources) instead
        // of the terminal error; once past it the missing data is definitive and the seek errors.
        it.each([
            {
                description: 'buffers and keeps polling while a recent recording is still ingesting',
                withinGracePeriod: true,
                expectedError: null,
                expectedBuffering: true,
                expectedWaitingForIngestion: true,
            },
            {
                description: 'errors once the ingestion grace period has elapsed',
                withinGracePeriod: false,
                expectedError: 'noPlayableFullSnapshot',
                expectedBuffering: false,
                expectedWaitingForIngestion: false,
            },
        ])('$description', ({ withinGracePeriod, expectedError, expectedBuffering, expectedWaitingForIngestion }) => {
            const graceSpy = jest
                .spyOn(sessionRecordingDataCoordinatorLogicModule, 'isWithinIngestionGracePeriod')
                .mockReturnValue(withinGracePeriod)
            try {
                seedRecording([inc(START), inc(START + 1000)], [inc(START + 61000), inc(START + 62000)])
                logic.actions.setPause()

                logic.actions.seekToTimestamp(START + 61500)

                expect(logic.values.playerError).toBe(expectedError)
                expect(logic.values.isBuffering).toBe(expectedBuffering)
                expect(logic.values.isWaitingForIngestion).toBe(expectedWaitingForIngestion)
                expect(logic.values.currentTimestamp).toBe(START + 61500)
            } finally {
                graceSpy.mockRestore()
            }
        })

        it('flips a stuck still-ingesting recording to the terminal error once grace lapses', () => {
            // The afterMount BUFFERING_REEVALUATION_INTERVAL_MS interval re-runs checkBufferingCompleted;
            // this asserts that payload directly (no timer): a recording buffering on waitingForIngestion
            // transitions to the terminal error the next time checkBufferingCompleted runs after the grace
            // period has elapsed — without any new snapshot data arriving.
            const graceSpy = jest
                .spyOn(sessionRecordingDataCoordinatorLogicModule, 'isWithinIngestionGracePeriod')
                .mockReturnValue(true)
            try {
                seedRecording([inc(START), inc(START + 1000)], [inc(START + 61000), inc(START + 62000)])
                logic.actions.setPause()
                logic.actions.seekToTimestamp(START + 61500)
                expect(logic.values.isBuffering).toBe(true)
                expect(logic.values.playerError).toBeNull()

                // grace lapses, no new data arrives — the periodic nudge re-reads the now-definitive
                // verdict and surfaces the terminal error
                graceSpy.mockReturnValue(false)
                logic.actions.checkBufferingCompleted()

                expect(logic.values.playerError).toBe('noPlayableFullSnapshot')
            } finally {
                graceSpy.mockRestore()
            }
        })

        it.each([
            {
                description: 'reports the leading unplayable span when the initial full snapshot is late',
                firstSourceSnapshots: [inc(START), inc(START + 1000)],
                secondSourceSnapshots: [fs(LATE_FS_TS)],
                expectedLeadingUnplayableMs: LATE_FS_TS - START,
                expectedHasLate: true,
            },
            {
                description: 'reports no unplayable span when a full snapshot exists at the start',
                firstSourceSnapshots: [fs(START), inc(START + 1000)],
                secondSourceSnapshots: [inc(LATE_FS_TS)],
                expectedLeadingUnplayableMs: 0,
                expectedHasLate: false,
            },
            {
                description: 'reports no unplayable span when no full snapshot exists anywhere',
                firstSourceSnapshots: [inc(START), inc(START + 1000)],
                secondSourceSnapshots: [inc(START + 61000), inc(START + 62000)],
                expectedLeadingUnplayableMs: 0,
                expectedHasLate: false,
            },
            {
                description: 'measures the span but does not flag a late snapshot below the warning threshold',
                firstSourceSnapshots: [inc(START), fs(START + 5000)],
                secondSourceSnapshots: [inc(LATE_FS_TS)],
                expectedLeadingUnplayableMs: 5000,
                expectedHasLate: false,
            },
            {
                // multi-window: the first window renders from its own start, so a later window
                // lacking a full snapshot must not extend the leading unplayable span
                description: 'does not flag when the first window renders but a later window lacks a full snapshot',
                firstSourceSnapshots: [fs(START), inc(START + 1000)],
                secondSourceSnapshots: [w2inc(START + 61000), w2inc(START + 62000)],
                expectedLeadingUnplayableMs: 0,
                expectedHasLate: false,
            },
        ])(
            '$description',
            ({ firstSourceSnapshots, secondSourceSnapshots, expectedLeadingUnplayableMs, expectedHasLate }) => {
                seedRecording(firstSourceSnapshots, secondSourceSnapshots)

                expect(logic.values.leadingUnplayableMs).toBe(expectedLeadingUnplayableMs)
                expect(logic.values.hasLateFullSnapshot).toBe(expectedHasLate)
            }
        )
    })

    describe('delete session recording', () => {
        const mockedDeleteRecording = deleteRecordingMock as jest.MockedFunction<typeof deleteRecordingMock>

        beforeEach(() => {
            mockedDeleteRecording.mockResolvedValue(undefined)
        })

        it('calls onRecordingDeleted callback when provided', async () => {
            silenceKeaLoadersErrors()
            const onRecordingDeleted = jest.fn()
            logic = sessionRecordingPlayerLogic({
                sessionRecordingId: '3',
                playerKey: 'test',
                blobV2PollingDisabled: true,
                onRecordingDeleted,
            })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.deleteRecording()
            })
                .toDispatchActions(['deleteRecording'])
                .toFinishAllListeners()

            expect(mockedDeleteRecording).toHaveBeenCalledWith('3')
            expect(onRecordingDeleted).toHaveBeenCalled()
            resumeKeaLoadersErrors()
        })

        it('does not navigate away after delete', async () => {
            silenceKeaLoadersErrors()
            logic = sessionRecordingPlayerLogic({
                sessionRecordingId: '3',
                playerKey: 'test',
                blobV2PollingDisabled: true,
            })
            logic.mount()
            router.actions.push(urls.replaySingle('3'))
            const pathBefore = router.values.location.pathname

            await expectLogic(logic, () => {
                logic.actions.deleteRecording()
            })
                .toDispatchActions(['deleteRecording'])
                .toFinishAllListeners()

            expect(router.values.location.pathname).toEqual(pathBefore)
            expect(mockedDeleteRecording).toHaveBeenCalledWith('3')
            resumeKeaLoadersErrors()
        })

        it('does not mark recording as deleted when API call fails', async () => {
            silenceKeaLoadersErrors()
            mockedDeleteRecording.mockRejectedValue(new Error('API error'))

            logic = sessionRecordingPlayerLogic({
                sessionRecordingId: '3',
                playerKey: 'test',
                blobV2PollingDisabled: true,
            })
            logic.mount()
            deletedRecordingsLogic.mount()

            await expectLogic(logic, () => {
                logic.actions.deleteRecording()
            })
                .toDispatchActions(['deleteRecording'])
                .toFinishAllListeners()

            expect(deletedRecordingsLogic.values.deletedRecordingIds.has('3')).toBe(false)
            resumeKeaLoadersErrors()
        })
    })

    describe('matching', () => {
        const listOfMatchingEvents = [
            { uuid: '1', timestamp: '2022-06-01T12:00:00.000Z', session_id: '1', window_id: '1' },
            { uuid: '2', timestamp: '2022-06-01T12:01:00.000Z', session_id: '1', window_id: '1' },
            { uuid: '3', timestamp: '2022-06-01T12:02:00.000Z', session_id: '1', window_id: '1' },
        ]

        it('initialized through props', async () => {
            logic = sessionRecordingPlayerLogic({
                sessionRecordingId: '3',
                playerKey: 'test',
                matchingEventsMatchType: {
                    matchType: 'uuid',
                    matchedEvents: listOfMatchingEvents,
                },
            })
            logic.mount()
            await expectLogic(logic).toMatchValues({
                logicProps: expect.objectContaining({
                    matchingEventsMatchType: {
                        matchType: 'uuid',
                        matchedEvents: listOfMatchingEvents,
                    },
                }),
            })
        })
        it('changes when filter results change', async () => {
            logic = sessionRecordingPlayerLogic({
                sessionRecordingId: '4',
                playerKey: 'test',
                matchingEventsMatchType: {
                    matchType: 'uuid',
                    matchedEvents: listOfMatchingEvents,
                },
            })
            logic.mount()
            await expectLogic(logic).toMatchValues({
                logicProps: expect.objectContaining({
                    matchingEventsMatchType: {
                        matchType: 'uuid',
                        matchedEvents: listOfMatchingEvents,
                    },
                }),
            })
            logic = sessionRecordingPlayerLogic({
                sessionRecordingId: '4',
                playerKey: 'test',
                matchingEventsMatchType: {
                    matchType: 'uuid',
                    matchedEvents: listOfMatchingEvents.slice(0, 1),
                },
            })
            logic.mount()
            await expectLogic(logic).toMatchValues({
                logicProps: expect.objectContaining({
                    matchingEventsMatchType: {
                        matchType: 'uuid',
                        matchedEvents: listOfMatchingEvents.slice(0, 1),
                    },
                }),
            })
        })
    })

    describe('the logger override', () => {
        it('captures replayer warnings and logs to window stores', () => {
            const categories: string[] = []
            const logger = makeLogger((category) => categories.push(category))

            logger.logger.warn('[replayer]', 'test')
            logger.logger.warn('[replayer]', 'test2')
            logger.logger.log('[replayer]', 'test3')

            expect((window as any).__posthog_player_warnings).toEqual([
                ['[replayer]', 'test'],
                ['[replayer]', 'test2'],
            ])
            expect((window as any).__posthog_player_logs).toEqual([['[replayer]', 'test3']])
            expect(categories).toEqual(['test', 'test2'])
        })

        it('calls onWarning with categorized message per warning', () => {
            const categories: string[] = []
            const logger = makeLogger((category) => categories.push(category))

            logger.logger.warn('[replayer]', 'Unknown tag: custom-element')
            logger.logger.warn('[replayer]', 'Unknown tag: custom-element')
            logger.logger.warn('[replayer]', 'Mutation target not found')

            expect(categories).toEqual([
                'Unknown tag: custom-element',
                'Unknown tag: custom-element',
                'Mutation target not found',
            ])
        })

        it('filters out ignored warnings', () => {
            const categories: string[] = []
            const logger = makeLogger((category) => categories.push(category))

            logger.logger.warn('[replayer]', 'Could not find node with id 42. Skipping mutation.')
            logger.logger.warn('[replayer]', 'Could not find node with id 99. Skipping mutation.')
            logger.logger.warn('[replayer]', 'Unknown tag: custom-element')

            expect(categories).toEqual(['Unknown tag: custom-element'])
        })
    })

    describe('recording viewed summary event', () => {
        describe('play_time_ms tracking', () => {
            const startPlaying = (): void => {
                logic.actions.setPlay()
                logic.actions.endBuffer()
            }

            beforeEach(() => {
                jest.useFakeTimers({
                    now: new Date('2024-02-07T00:00:01.123Z'),
                })
                logic.unmount()
                logic = sessionRecordingPlayerLogic({ sessionRecordingId: '2', playerKey: 'test' })
                logic.mount()
            })

            it('initializes playingTimeTracking correctly', () => {
                expect(logic.values.playingTimeTracking).toEqual({
                    state: 'paused',
                    lastTimestamp: null,
                    watchTime: 0,
                    bufferTime: 0,
                    firstPlayTime: undefined,
                    firstPlayStartTime: undefined,
                })
            })

            it('sets buffering state with startBuffer', () => {
                expect(logic.values.playingTimeTracking.lastTimestamp).toBeNull()

                logic.actions.setPlay()
                logic.actions.startBuffer()

                expect(logic.values.playingTimeTracking.state).toBe('buffering')
                expect(logic.values.playingTimeTracking.lastTimestamp).not.toBeNull()
            })

            it('tracks buffer time', () => {
                logic.actions.setPlay()
                logic.actions.startBuffer()
                jest.advanceTimersByTime(1500)
                logic.actions.endBuffer()

                expect(logic.values.playingTimeTracking.bufferTime).toBe(1500)
                expect(logic.values.playingTimeTracking.watchTime).toBe(0)
            })

            it('transitions to playing after endBuffer', () => {
                startPlaying()

                expect(logic.values.playingTimeTracking.state).toBe('playing')
            })

            it('accumulates watch time during play', () => {
                startPlaying()
                jest.advanceTimersByTime(1000)
                logic.actions.setPause()

                expect(logic.values.playingTimeTracking.watchTime).toBe(1000)
            })

            it('separates play and buffer time when alternating', () => {
                const playFor = (ms: number): void => {
                    startPlaying()
                    jest.advanceTimersByTime(ms)
                    logic.actions.setPause()
                }

                const bufferFor = (ms: number): void => {
                    logic.actions.startBuffer()
                    jest.advanceTimersByTime(ms)
                    logic.actions.endBuffer()
                }

                playFor(1000)
                bufferFor(1000)
                playFor(1000)
                bufferFor(1000)
                playFor(1000)
                bufferFor(1000)
                playFor(1000)

                expect(logic.values.playingTimeTracking.watchTime).toBe(4000)
                expect(logic.values.playingTimeTracking.bufferTime).toBe(3000)
            })

            it('preserves buffer time on repeated endBuffer calls', () => {
                logic.actions.setPlay()
                logic.actions.startBuffer()
                jest.advanceTimersByTime(1000)
                logic.actions.endBuffer()

                const bufferTime = logic.values.playingTimeTracking.bufferTime

                logic.actions.endBuffer()
                logic.actions.endBuffer()
                logic.actions.endBuffer()

                expect(logic.values.playingTimeTracking.bufferTime).toBe(bufferTime)
            })

            describe('time_to_first_play_ms tracking', () => {
                it('preserves firstPlayTime after buffer interrupts post-threshold', () => {
                    startPlaying()
                    jest.advanceTimersByTime(1000)
                    jest.runOnlyPendingTimers()

                    expect(logic.values.playingTimeTracking.firstPlayTime).toBe(0)

                    logic.actions.startBuffer()
                    jest.runOnlyPendingTimers()

                    expect(logic.values.playingTimeTracking.firstPlayTime).toBe(0)
                })

                it('records firstPlayTime only once', () => {
                    startPlaying()
                    jest.advanceTimersByTime(1000)
                    jest.runOnlyPendingTimers()

                    const firstPlayTime = logic.values.playingTimeTracking.firstPlayTime

                    logic.actions.setPause()
                    logic.actions.setPlay()
                    jest.advanceTimersByTime(2000)
                    jest.runOnlyPendingTimers()

                    expect(logic.values.playingTimeTracking.firstPlayTime).toBe(firstPlayTime)
                })

                it('retries tracking after early interruption', () => {
                    jest.advanceTimersByTime(500)

                    logic.actions.setPause()
                    expect(logic.values.playingTimeTracking.firstPlayTime).toBeUndefined()

                    startPlaying()
                    jest.runOnlyPendingTimers()

                    expect(logic.values.playingTimeTracking.firstPlayTime).toBe(500)
                })
            })
        })

        describe('recording viewed summary analytics', () => {
            it('captures all required analytics properties on unmount', () => {
                jest.useFakeTimers()
                logic.unmount()
                logic = sessionRecordingPlayerLogic({ sessionRecordingId: '2', playerKey: 'test' })
                logic.mount()

                const mockCapture = jest.fn()
                ;(posthog as any).capture = mockCapture

                logic.actions.setPlay()
                logic.actions.endBuffer()
                jest.advanceTimersByTime(1001)
                logic.actions.setPause()

                logic.actions.incrementClickCount()
                logic.cache.rrwebWarningCount = 2
                logic.actions.incrementErrorCount()

                logic.unmount()

                expect(mockCapture).toHaveBeenCalledWith(
                    'recording viewed summary',
                    expect.objectContaining({
                        viewed_time_ms: expect.any(Number),
                        play_time_ms: expect.any(Number),
                        buffer_time_ms: expect.any(Number),
                        time_to_first_play_ms: expect.any(Number),
                        rrweb_warning_count: 2,
                        error_count_during_recording_playback: 1,
                        engagement_score: 1,
                        recording_duration_ms: 0,
                        recording_age_ms: undefined,
                    })
                )
                expect(mockCapture.mock.calls[0][1].time_to_first_play_ms).toBe(0)
            })

            it('captures "no playtime summary" event when play_time_ms is 0', async () => {
                const mockCapture = jest.fn()
                ;(posthog as any).capture = mockCapture

                logic.unmount()

                expect(mockCapture).toHaveBeenCalledWith(
                    'recording viewed with no playtime summary',
                    expect.objectContaining({
                        viewed_time_ms: expect.any(Number),
                        play_time_ms: 0,
                        buffer_time_ms: 0,
                        engagement_score: 0,
                    })
                )
            })

            it('calculates engagement score based on click count', async () => {
                const mockCapture = jest.fn()
                ;(posthog as any).capture = mockCapture

                logic.actions.incrementClickCount()
                logic.actions.incrementClickCount()
                logic.actions.incrementClickCount()

                logic.unmount()

                expect(mockCapture).toHaveBeenCalledWith(
                    'recording viewed with no playtime summary',
                    expect.objectContaining({
                        engagement_score: 3,
                    })
                )
            })
        })
    })

    describe('seek actions', () => {
        it('seekForward without parameter uses default jumpTimeMs (10s)', () => {
            const currentTime = 5000
            logic.actions.seekToTime(currentTime)

            const jumpTimeMs = logic.values.jumpTimeMs
            expect(jumpTimeMs).toBe(10000) // 10s * speed(1)

            logic.actions.seekForward()
            // seekForward should call seekToTime with current time + jumpTimeMs
        })

        it('seekBackward without parameter uses default jumpTimeMs (10s)', () => {
            const currentTime = 15000
            logic.actions.seekToTime(currentTime)

            const jumpTimeMs = logic.values.jumpTimeMs
            expect(jumpTimeMs).toBe(10000) // 10s * speed(1)

            logic.actions.seekBackward()
            // seekBackward should call seekToTime with current time - jumpTimeMs
        })

        it('seekForward with 1000ms parameter jumps forward 1s', () => {
            const currentTime = 5000
            logic.actions.seekToTime(currentTime)
            logic.actions.seekForward(1000)
            // seekForward should call seekToTime with current time + 1000
        })

        it('seekBackward with 1000ms parameter jumps backward 1s', () => {
            const currentTime = 5000
            logic.actions.seekToTime(currentTime)
            logic.actions.seekBackward(1000)
            // seekBackward should call seekToTime with current time - 1000
        })

        it('seekForward respects custom amount parameter', () => {
            const currentTime = 5000
            const customAmount = 2500
            logic.actions.seekToTime(currentTime)
            logic.actions.seekForward(customAmount)
            // seekForward should call seekToTime with current time + customAmount
        })

        it('seekBackward respects custom amount parameter', () => {
            const currentTime = 5000
            const customAmount = 3500
            logic.actions.seekToTime(currentTime)
            logic.actions.seekBackward(customAmount)
            // seekBackward should call seekToTime with current time - customAmount
        })

        it('default jumpTimeMs scales with playback speed', () => {
            logic.actions.setSpeed(2)

            const jumpTimeMs = logic.values.jumpTimeMs
            expect(jumpTimeMs).toBe(20000) // 10s * speed(2)

            logic.actions.seekToTime(5000)
            logic.actions.seekForward()
            // seekForward should call seekToTime with current time + 20000
        })
    })

    describe('setCurrentSegment graceful fallback', () => {
        it('starts buffering instead of tryInitReplayer when segment windowId has no snapshots', () => {
            const tryInitReplayerSpy = jest.spyOn(logic.actions, 'tryInitReplayer')
            const startBufferSpy = jest.spyOn(logic.actions, 'startBuffer')

            // Clear any calls from initialization
            tryInitReplayerSpy.mockClear()
            startBufferSpy.mockClear()

            // Segment with windowId that has no snapshots loaded
            const segmentWithNoSnapshots = {
                kind: 'window' as const,
                startTimestamp: 1000,
                endTimestamp: 2000,
                windowId: 99999, // non-existent window id
                isActive: true,
                durationMs: 1000,
            }

            logic.actions.setCurrentSegment(segmentWithNoSnapshots)

            expect(tryInitReplayerSpy).not.toHaveBeenCalled()
            expect(startBufferSpy).toHaveBeenCalled()
        })

        it('keeps current player for gap segments without calling tryInitReplayer', () => {
            const tryInitReplayerSpy = jest.spyOn(logic.actions, 'tryInitReplayer')
            const startBufferSpy = jest.spyOn(logic.actions, 'startBuffer')

            // Clear any calls from initialization
            tryInitReplayerSpy.mockClear()
            startBufferSpy.mockClear()

            const gapSegment = {
                kind: 'gap' as const,
                startTimestamp: 1000,
                endTimestamp: 2000,
                windowId: 99999,
                isActive: false,
                durationMs: 1000,
            }

            logic.actions.setCurrentSegment(gapSegment)

            expect(tryInitReplayerSpy).not.toHaveBeenCalled()
            expect(startBufferSpy).not.toHaveBeenCalled()
        })

        it('keeps current player when segment has no windowId', () => {
            const tryInitReplayerSpy = jest.spyOn(logic.actions, 'tryInitReplayer')

            // Clear any calls from initialization
            tryInitReplayerSpy.mockClear()

            const segmentWithNoWindowId = {
                kind: 'buffer' as const,
                startTimestamp: 1000,
                endTimestamp: 2000,
                windowId: undefined,
                isActive: false,
                durationMs: 1000,
            }

            logic.actions.setCurrentSegment(segmentWithNoWindowId)

            expect(tryInitReplayerSpy).not.toHaveBeenCalled()
        })
    })

    describe('exportRecording', () => {
        it('uses the player skip-inactivity setting', () => {
            // setRootFrame clears innerHTML, so append the iframe after it runs
            const rootFrame = document.createElement('div')
            logic.actions.setRootFrame(rootFrame)
            rootFrame.appendChild(document.createElement('iframe'))

            playerSettingsLogic.actions.setSkipInactivitySetting(false)

            const startReplayExportSpy = jest.spyOn(logic.actions, 'startReplayExport')
            logic.actions.exportRecording(ExporterFormat.MP4, 0, SessionRecordingPlayerMode.Video, 3600)

            expect(startReplayExportSpy).toHaveBeenCalledTimes(1)
            expect(startReplayExportSpy.mock.calls[0]?.[5]?.skip_inactivity).toBe(false)
            startReplayExportSpy.mockRestore()
        })
    })
})
