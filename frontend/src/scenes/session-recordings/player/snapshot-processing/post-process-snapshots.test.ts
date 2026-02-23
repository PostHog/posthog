import { EventType } from '@posthog/rrweb-types'

import { RecordingSnapshot } from '~/types'

import { createPostProcessingState, postProcessSnapshots } from './post-process-snapshots'

jest.mock('posthog-js', () => ({
    __esModule: true,
    default: {
        capture: jest.fn(),
        captureException: jest.fn(),
    },
}))

function makeSnapshot(overrides: Record<string, any> & { timestamp: number; type: number }): RecordingSnapshot {
    return {
        windowId: 1,
        data: {},
        ...overrides,
    } as unknown as RecordingSnapshot
}

function makeFullSnapshot(timestamp: number, windowId = 1, nodeData?: any): RecordingSnapshot {
    return {
        type: EventType.FullSnapshot,
        timestamp,
        windowId,
        data: {
            node: nodeData ?? {
                type: 0,
                childNodes: [
                    {
                        type: 2,
                        tagName: 'html',
                        attributes: {},
                        childNodes: [
                            { type: 2, tagName: 'head', attributes: {}, childNodes: [] },
                            { type: 2, tagName: 'body', attributes: {}, childNodes: [] },
                        ],
                    },
                ],
            },
            initialOffset: { top: 0, left: 0 },
        },
    } as unknown as RecordingSnapshot
}

function makeMobileIncrementalScreenshot(
    timestamp: number,
    windowId = 1,
    width = 400,
    height = 800
): RecordingSnapshot {
    return {
        type: EventType.IncrementalSnapshot,
        timestamp,
        windowId,
        data: {
            source: 0,
            adds: [
                {
                    parentId: 5,
                    nextId: null,
                    node: {
                        type: 2,
                        tagName: 'img',
                        id: 100,
                        attributes: {
                            'data-rrweb-id': 100,
                            width,
                            height,
                            src: 'data:image/png;base64,test',
                        },
                        childNodes: [],
                    },
                },
            ],
            removes: [],
            texts: [],
            attributes: [],
        },
    } as unknown as RecordingSnapshot
}

function makeMetaSnapshot(timestamp: number, windowId = 1): RecordingSnapshot {
    return {
        type: EventType.Meta,
        timestamp,
        windowId,
        data: { width: 1920, height: 1080, href: 'https://example.com' },
    } as unknown as RecordingSnapshot
}

describe('postProcessSnapshots', () => {
    describe('deduplication', () => {
        it.each([
            {
                name: 'drops duplicate snapshots at the same timestamp',
                input: [
                    makeSnapshot({ type: 3, timestamp: 1000, data: { source: 1, payload: 'a' } }),
                    makeSnapshot({ type: 3, timestamp: 1000, data: { source: 1, payload: 'a' } }),
                ],
                expectedCount: 1,
            },
            {
                name: 'keeps unique snapshots at the same timestamp',
                input: [
                    makeSnapshot({ type: 3, timestamp: 1000, data: { source: 1, payload: 'a' } }),
                    makeSnapshot({ type: 3, timestamp: 1000, data: { source: 1, payload: 'b' } }),
                ],
                expectedCount: 2,
            },
            {
                name: 'does not dedup snapshots at different timestamps',
                input: [
                    makeSnapshot({ type: 3, timestamp: 1000, data: { source: 1, payload: 'a' } }),
                    makeSnapshot({ type: 3, timestamp: 2000, data: { source: 1, payload: 'a' } }),
                ],
                expectedCount: 2,
            },
            {
                name: 'handles interspersed duplicates and uniques at same timestamp',
                input: [
                    makeSnapshot({ type: 3, timestamp: 1000, data: { source: 1, payload: 'a' } }),
                    makeSnapshot({ type: 3, timestamp: 1000, data: { source: 1, payload: 'b' } }),
                    makeSnapshot({ type: 3, timestamp: 1000, data: { source: 1, payload: 'a' } }),
                ],
                expectedCount: 2,
            },
        ])('$name', async ({ input, expectedCount }) => {
            const state = createPostProcessingState()
            const result = await postProcessSnapshots(input, state, 'test-session')
            expect(result).toHaveLength(expectedCount)
        })
    })

    describe('chrome extension stripping', () => {
        it('strips chrome extension data from full snapshots and inserts custom event', async () => {
            const nodeWithExtension = {
                type: 0,
                childNodes: [
                    {
                        type: 2,
                        tagName: 'html',
                        attributes: {},
                        childNodes: [
                            { type: 2, tagName: 'head', attributes: {}, childNodes: [] },
                            {
                                type: 2,
                                tagName: 'body',
                                attributes: {},
                                childNodes: [
                                    {
                                        type: 2,
                                        tagName: 'div',
                                        attributes: {
                                            id: 'dji-sru',
                                        },
                                        childNodes: [
                                            {
                                                type: 3,
                                                textContent: 'extension content',
                                            },
                                        ],
                                    },
                                ],
                            },
                        ],
                    },
                ],
            }

            const state = createPostProcessingState()
            const input = [makeFullSnapshot(1000, 1, nodeWithExtension)]
            const result = await postProcessSnapshots(input, state, 'test-session')

            const customEvents = result.filter((s) => s.type === EventType.Custom)
            expect(customEvents).toHaveLength(1)
            expect((customEvents[0] as any).data.tag).toBe('chrome-extension-stripped')
            expect((customEvents[0] as any).data.payload.extensions).toContain('snap and read')
        })

        it('does not insert custom event for clean full snapshots', async () => {
            const state = createPostProcessingState()
            const input = [makeFullSnapshot(1000)]
            const result = await postProcessSnapshots(input, state, 'test-session')

            const customEvents = result.filter((s) => s.type === EventType.Custom)
            expect(customEvents).toHaveLength(0)
            expect(result).toHaveLength(1)
        })
    })

    describe('mobile meta-event patching', () => {
        it('inserts synthetic full snapshot and meta for mobile incremental with no prior full', async () => {
            const state = createPostProcessingState()
            const input = [makeMobileIncrementalScreenshot(1000)]
            const result = await postProcessSnapshots(input, state, 'test-session')

            const fullSnapshots = result.filter((s) => s.type === EventType.FullSnapshot)
            const metaSnapshots = result.filter((s) => s.type === EventType.Meta)

            expect(fullSnapshots).toHaveLength(1)
            expect(fullSnapshots[0].timestamp).toBe(999)
            expect(metaSnapshots).toHaveLength(1)
            expect(metaSnapshots[0].timestamp).toBe(999)
            expect((metaSnapshots[0] as any).data.width).toBe(400)
            expect((metaSnapshots[0] as any).data.height).toBe(800)
        })

        it('inserts synthetic full but no meta when window already has a full snapshot', async () => {
            const state = createPostProcessingState()
            const input = [makeFullSnapshot(500), makeMobileIncrementalScreenshot(1000)]

            // Need a meta before the full snapshot so pushPatchedMeta doesn't fire for it
            const inputWithMeta = [makeMetaSnapshot(499), ...input]
            const result = await postProcessSnapshots(inputWithMeta, state, 'test-session')

            const fullSnapshots = result.filter((s) => s.type === EventType.FullSnapshot)
            const metaSnapshots = result.filter((s) => s.type === EventType.Meta)

            // 1 original full + 1 synthetic full
            expect(fullSnapshots).toHaveLength(2)
            // 1 original meta (the one we added) + 0 patched (window already has full)
            expect(metaSnapshots).toHaveLength(1)
        })

        it('uses viewportForTimestamp as fallback for web full snapshots without meta', async () => {
            const state = createPostProcessingState()
            const viewport = { width: '1920', height: '1080', href: 'https://example.com' }
            const viewportFn = jest.fn().mockReturnValue(viewport)

            const input = [makeFullSnapshot(1000)]
            const result = await postProcessSnapshots(input, state, 'test-session', viewportFn)

            const metaSnapshots = result.filter((s) => s.type === EventType.Meta)
            expect(metaSnapshots).toHaveLength(1)
            expect((metaSnapshots[0] as any).data.width).toBe(1920)
            expect((metaSnapshots[0] as any).data.height).toBe(1080)
        })

        it('does not patch meta when Meta event already exists before full snapshot', async () => {
            const state = createPostProcessingState()
            const input = [makeMetaSnapshot(999), makeFullSnapshot(1000)]
            const result = await postProcessSnapshots(input, state, 'test-session')

            const metaSnapshots = result.filter((s) => s.type === EventType.Meta)
            // Only the original meta, no patched one
            expect(metaSnapshots).toHaveLength(1)
            expect(metaSnapshots[0].timestamp).toBe(999)
        })
    })

    describe('cross-source state persistence', () => {
        it('persists seenFullByWindow across calls', async () => {
            const state = createPostProcessingState()

            // First batch: full snapshot for window 1
            await postProcessSnapshots([makeMetaSnapshot(499), makeFullSnapshot(500)], state, 'test-session')
            expect(state.seenFullByWindow[1]).toBe(true)

            // Second batch: mobile screenshot for same window — no new meta patched
            const result = await postProcessSnapshots([makeMobileIncrementalScreenshot(1000)], state, 'test-session')

            // Synthetic full is still created, but no new meta
            const metaSnapshots = result.filter((s) => s.type === EventType.Meta)
            expect(metaSnapshots).toHaveLength(0)
        })
    })

    describe('yielding', () => {
        it('yields to main thread during large batches', async () => {
            const originalPerformanceNow = performance.now
            let callCount = 0

            // Mock performance.now to simulate time passing
            jest.spyOn(performance, 'now').mockImplementation(() => {
                callCount++
                // Return increasing time: each call advances 10ms
                return callCount * 10
            })

            const setTimeoutSpy = jest.spyOn(global, 'setTimeout')

            const state = createPostProcessingState()
            const snapshots = Array.from({ length: 20 }, (_, i) =>
                makeSnapshot({ type: 3, timestamp: 1000 + i, data: { source: 1, value: i } })
            )

            await postProcessSnapshots(snapshots, state, 'test-session')

            // setTimeout should have been called for yielding (at least once since 20 * 10ms > 50ms)
            const yieldCalls = setTimeoutSpy.mock.calls.filter((call) => call[1] === 0 && typeof call[0] === 'function')
            expect(yieldCalls.length).toBeGreaterThan(0)

            performance.now = originalPerformanceNow
            setTimeoutSpy.mockRestore()
        })
    })

    describe('empty input', () => {
        it('returns empty array for empty input', async () => {
            const state = createPostProcessingState()
            const result = await postProcessSnapshots([], state, 'test-session')
            expect(result).toEqual([])
        })
    })
})
