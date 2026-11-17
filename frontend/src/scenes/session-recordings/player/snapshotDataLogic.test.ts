import { expectLogic } from 'kea-test-utils'
import { HttpResponse } from 'msw'
import posthog from 'posthog-js'
import { EventType, IncrementalSource, NodeType, mutationData } from 'posthog-js/rrweb-types'

import { chunkMutationSnapshot, MUTATION_CHUNK_SIZE } from '@posthog/replay-shared'

import { ApiError, RecordingDeletedError } from 'lib/api'
import { encodedWebSnapshotData } from 'scenes/session-recordings/player/__mocks__/encoded-snapshot-data'
import { parseEncodedSnapshots } from 'scenes/session-recordings/player/snapshot-processing/process-all-snapshots'

import { RecordingSnapshot, SessionRecordingSnapshotSource } from '~/types'

import { snapshotsAsJSONLines } from '../__mocks__/recording_snapshots'
import { overrideSessionRecordingMocks, setupSessionRecordingTest } from './__mocks__/test-setup'
import { snapshotDataLogic } from './snapshotDataLogic'

const BLOB_SOURCE: SessionRecordingSnapshotSource = {
    source: 'blob_v2',
    start_timestamp: '2023-08-11T12:03:36.097000Z',
    end_timestamp: '2023-08-11T12:04:52.268000Z',
    blob_key: '0',
}
const BLOB_SOURCE_TWO: SessionRecordingSnapshotSource = {
    source: 'blob_v2',
    start_timestamp: '2023-08-11T12:04:53.097000Z',
    end_timestamp: '2023-08-11T12:04:56.268000Z',
    blob_key: '1',
}

describe('snapshotDataLogic', () => {
    let logic: ReturnType<typeof snapshotDataLogic.build>

    beforeEach(() => {
        setupSessionRecordingTest({
            snapshotSources: [BLOB_SOURCE, BLOB_SOURCE_TWO],
        })
        logic = snapshotDataLogic({
            sessionRecordingId: '2',
            blobV2PollingDisabled: true,
        })
        logic.mount()
    })

    describe('recording deleted selectors', () => {
        it('isRecordingDeleted is false when no error', () => {
            expect(logic.values.isRecordingDeleted).toBe(false)
            expect(logic.values.recordingDeletedAt).toBe(null)
            expect(logic.values.recordingDeletedBy).toBe(null)
        })

        it('isRecordingDeleted is true when snapshotLoadError is RecordingDeletedError', () => {
            const error = new RecordingDeletedError(1700000000, 'admin@example.com')
            logic.actions.loadSnapshotsForSourceFailure('Recording deleted', error)

            expect(logic.values.isRecordingDeleted).toBe(true)
            expect(logic.values.recordingDeletedAt).toBe(1700000000)
            expect(logic.values.recordingDeletedBy).toBe('admin@example.com')
        })

        it('isRecordingDeleted is false for non-deleted errors', () => {
            logic.actions.loadSnapshotsForSourceFailure('some error', new Error('some other error'))

            expect(logic.values.isRecordingDeleted).toBe(false)
            expect(logic.values.recordingDeletedAt).toBe(null)
            expect(logic.values.recordingDeletedBy).toBe(null)
        })

        it('marks the recording deleted when the sources listing returns 410, and a later block load keeps it so', async () => {
            overrideSessionRecordingMocks({
                getMocks: {
                    '/api/environments/:team_id/session_recordings/:id/snapshots': () => [
                        410,
                        { error: 'recording_deleted', deleted_at: 1700000000, deleted_by: 'admin@example.com' },
                    ],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.loadSnapshotSources()
            })
                .toDispatchActions(['loadSnapshotSourcesFailure'])
                .toMatchValues({ isRecordingDeleted: true, recordingDeletedBy: 'admin@example.com' })

            logic.actions.loadSnapshotsForSourceSuccess({ sources: [BLOB_SOURCE] })
            expect(logic.values.isRecordingDeleted).toBe(true)
        })

        it('recordingDeletedAt is null when deleted_at is not provided', () => {
            const error = new RecordingDeletedError(null, null)
            logic.actions.loadSnapshotsForSourceFailure('Recording deleted', error)

            expect(logic.values.isRecordingDeleted).toBe(true)
            expect(logic.values.recordingDeletedAt).toBe(null)
            expect(logic.values.recordingDeletedBy).toBe(null)
        })
    })

    describe('source load give-up', () => {
        it('dispatches snapshotSourceLoadExhausted once retries are exhausted', async () => {
            const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {})
            await expectLogic(logic, () => {
                logic.actions.loadSnapshotsForSourceFailure('load failed', new Error('load failed'))
                logic.actions.loadSnapshotsForSourceFailure('load failed', new Error('load failed'))
                logic.actions.loadSnapshotsForSourceFailure('load failed', new Error('load failed'))
                logic.actions.loadSnapshotsForSourceFailure('load failed', new Error('load failed'))
            }).toDispatchActions(['snapshotSourceLoadExhausted'])
            consoleError.mockRestore()
        })

        it('gives up on the first 429, because retrying within seconds cannot outlast the per-user quota', async () => {
            const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {})
            await expectLogic(logic, () => {
                logic.actions.loadSnapshotsForSourceFailure('Too many requests', new ApiError('Throttled', 429))
            })
                .toDispatchActions(['snapshotSourceLoadExhausted'])
                .toMatchValues({ snapshotLoadErrorKind: 'snapshotRateLimited' })
            consoleError.mockRestore()
        })

        it('re-arms the retry budget after retrySnapshotLoading, so a later failure is not instantly exhausted', async () => {
            const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {})
            // Exhaust the budget; consume the terminal action so it is out of the recording window.
            await expectLogic(logic, () => {
                logic.actions.loadSnapshotsForSourceFailure('load failed', new Error('load failed'))
                logic.actions.loadSnapshotsForSourceFailure('load failed', new Error('load failed'))
                logic.actions.loadSnapshotsForSourceFailure('load failed', new Error('load failed'))
                logic.actions.loadSnapshotsForSourceFailure('load failed', new Error('load failed'))
            }).toDispatchActions(['snapshotSourceLoadExhausted'])

            logic.actions.retrySnapshotLoading()

            // A single failure now must not re-trigger the terminal action — the budget was reset.
            await expectLogic(logic, () => {
                logic.actions.loadSnapshotsForSourceFailure('load failed', new Error('load failed'))
            }).toNotHaveDispatchedActions(['snapshotSourceLoadExhausted'])
            consoleError.mockRestore()
        })

        it('does not grant a permanently-unauthorized source a fresh retry budget on a new seek target', async () => {
            const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {})
            const error = new ApiError('Unauthorized', 401)
            logic.actions.loadSnapshotsForSourceFailure('Unauthorized', error)
            logic.actions.loadSnapshotsForSourceFailure('Unauthorized', error)
            logic.actions.loadSnapshotsForSourceFailure('Unauthorized', error)

            // Seeking to a genuinely new target would normally reset the retry budget, letting a
            // permanently-failing 401 source buffer forever instead of ever reaching the cap.
            logic.actions.setTargetTimestamp(123456, 1)

            await expectLogic(logic, () => {
                logic.actions.loadSnapshotsForSourceFailure('Unauthorized', error)
            }).toDispatchActions(['snapshotSourceLoadExhausted'])
            consoleError.mockRestore()
        })
    })

    describe('replay proxy token', () => {
        it.each([
            ['the token from the sources listing', 'header.payload.signature', 'header.payload.signature'],
            ['null when the listing has a null token', null, null],
            ['null when the listing has no token field', undefined, null],
        ])('stores %s', async (_, replayProxyToken, expected) => {
            overrideSessionRecordingMocks({ snapshotSources: [BLOB_SOURCE], replayProxyToken })

            await expectLogic(logic, () => {
                logic.actions.loadSnapshotSources()
            })
                .toDispatchActions(['loadSnapshotSourcesSuccess'])
                .toMatchValues({ replayProxyToken: expected })
        })
    })

    describe('direct block fetch', () => {
        const BLOCK_PATH = '/replay-blocks/1/2/u1/v1.ref0'
        const DIRECT_SOURCE: SessionRecordingSnapshotSource = {
            ...BLOB_SOURCE,
            url: BLOCK_PATH,
        }

        it.each([
            ['reads the block from its url', [200], 1, false, 'loadSnapshotsForSourceSuccess', null],
            [
                'falls back to the snapshots endpoint when the block fetch fails',
                [500],
                1,
                true,
                'loadSnapshotsForSourceSuccess',
                'http_error',
            ],
            [
                'falls back when the block route answers with the app shell',
                ['html'],
                1,
                true,
                'loadSnapshotsForSourceSuccess',
                'not_a_block',
            ],
            ['shows the recording as deleted on a 410', [410], 1, false, 'loadSnapshotsForSourceFailure', null],
            [
                'reads through the snapshots endpoint when a block url names another host',
                ['foreign'],
                0,
                true,
                'loadSnapshotsForSourceSuccess',
                null,
            ],
            [
                'retries a rate-limited block from recording-api instead of the snapshots endpoint',
                [429, 429, 200],
                3,
                false,
                'loadSnapshotsForSourceSuccess',
                null,
            ],
            ['reports a rate limit that outlasts every retry', [429], 4, false, 'loadSnapshotsForSourceFailure', null],
            [
                'falls back when a rate-limited retry gets another error',
                [429, 401],
                2,
                true,
                'loadSnapshotsForSourceSuccess',
                'http_error',
            ],
        ] as const)(
            '%s',
            async (_, blockStatuses, expectedBlockReads, expectsSnapshotsEndpoint, expectedAction, fallbackReason) => {
                const capture = jest.spyOn(posthog, 'capture')
                let snapshotsEndpointBlockReads = 0
                let blockReads = 0
                const blockRequestHeaders: { referrerPolicy: string; cookie: string | null }[] = []
                overrideSessionRecordingMocks({
                    getMocks: {
                        '/api/environments/:team_id/session_recordings/:id/snapshots': ({ request }) => {
                            if (new URL(request.url).searchParams.get('source') === 'blob_v2') {
                                snapshotsEndpointBlockReads += 1
                                return new HttpResponse(snapshotsAsJSONLines())
                            }
                            const source =
                                blockStatuses[0] === 'foreign'
                                    ? { ...DIRECT_SOURCE, url: `//attacker.example.com${BLOCK_PATH}` }
                                    : DIRECT_SOURCE
                            return [200, { sources: [source], block_token: 'block.token.sig' }]
                        },
                        [BLOCK_PATH]: ({ request }) => {
                            blockRequestHeaders.push({
                                referrerPolicy: request.referrerPolicy,
                                cookie: request.headers.get('cookie'),
                            })
                            const blockStatus = blockStatuses[Math.min(blockReads++, blockStatuses.length - 1)]
                            return blockStatus === 200
                                ? new HttpResponse(snapshotsAsJSONLines(), {
                                      headers: { 'Content-Type': 'application/octet-stream' },
                                  })
                                : blockStatus === 'html'
                                  ? new HttpResponse('<!doctype html><html></html>', {
                                        headers: { 'Content-Type': 'text/html' },
                                    })
                                  : blockStatus === 429
                                    ? new HttpResponse(JSON.stringify({ error: 'rate_limited' }), {
                                          status: 429,
                                          headers: { 'Content-Type': 'application/json', 'Retry-After': '1' },
                                      })
                                    : [blockStatus, { error: 'recording_deleted', deleted_at: 1700000000 }]
                        },
                    },
                })
                await expectLogic(logic, () => logic.actions.loadSnapshotSources()).toDispatchActions([
                    'loadSnapshotSourcesSuccess',
                ])

                // The retry waits run on fake timers, so the test advances them instead of waiting.
                jest.useFakeTimers({ doNotFake: ['nextTick', 'setImmediate', 'queueMicrotask'] })
                try {
                    logic.actions.loadSnapshotsForSource([DIRECT_SOURCE])
                    // Retry-After: 1 makes three retries take 3 seconds, where the fallback backoff would take 7.
                    await jest.advanceTimersByTimeAsync(4_000)
                } finally {
                    jest.useRealTimers()
                }
                await expectLogic(logic).toDispatchActions([expectedAction])

                expect(snapshotsEndpointBlockReads > 0).toBe(expectsSnapshotsEndpoint)
                expect(blockReads).toBe(expectedBlockReads)
                // Cookies and a long page URL as the Referer both push the headers past recording-api's size limit.
                expect(blockRequestHeaders).toEqual(
                    Array(expectedBlockReads).fill({ referrerPolicy: 'no-referrer', cookie: null })
                )
                expect(logic.values.isRecordingDeleted).toBe(blockStatuses[0] === 410)
                const fallbackEvents = capture.mock.calls.filter(
                    ([event]) => event === 'replay direct block fetch fell back'
                )
                expect(fallbackEvents.map(([, properties]) => properties?.reason)).toEqual(
                    fallbackReason ? [fallbackReason] : []
                )
                const rateLimitRetries = capture.mock.calls.filter(
                    ([event]) => event === 'replay direct block fetch rate limited'
                )
                expect(rateLimitRetries).toHaveLength(blockReads > 1 ? 1 : 0)
                capture.mockRestore()
            }
        )

        it.each([
            [
                'reports a pending rate limit when another block of the batch fails',
                'fails',
                [429],
                'loadSnapshotsForSourceFailure',
                false,
            ],
            [
                'falls back on a deadline once the rate-limited block has recovered',
                'stalls',
                [429, 200],
                'loadSnapshotsForSourceSuccess',
                true,
            ],
        ] as const)('%s', async (_, secondBlock, firstBlockStatuses, expectedAction, expectsSnapshotsEndpoint) => {
            const SECOND_BLOCK_PATH = '/replay-blocks/1/2/u1/v1.ref1'
            const secondSource: SessionRecordingSnapshotSource = {
                ...BLOB_SOURCE,
                blob_key: '1',
                url: SECOND_BLOCK_PATH,
            }
            let snapshotsEndpointBlockReads = 0
            let firstBlockReads = 0
            overrideSessionRecordingMocks({
                getMocks: {
                    '/api/environments/:team_id/session_recordings/:id/snapshots': ({ request }) => {
                        if (new URL(request.url).searchParams.get('source') === 'blob_v2') {
                            snapshotsEndpointBlockReads += 1
                            return new HttpResponse(snapshotsAsJSONLines())
                        }
                        return [200, { sources: [DIRECT_SOURCE, secondSource], block_token: 'block.token.sig' }]
                    },
                    [BLOCK_PATH]: () =>
                        firstBlockStatuses[Math.min(firstBlockReads++, firstBlockStatuses.length - 1)] === 429
                            ? new HttpResponse(JSON.stringify({ error: 'rate_limited' }), {
                                  status: 429,
                                  headers: { 'Content-Type': 'application/json', 'Retry-After': '1' },
                              })
                            : new HttpResponse(snapshotsAsJSONLines(), {
                                  headers: { 'Content-Type': 'application/octet-stream' },
                              }),
                    // Fails while the first block waits to retry, or stalls past the 30 second batch deadline.
                    [SECOND_BLOCK_PATH]: async () => {
                        await new Promise((resolve) => setTimeout(resolve, secondBlock === 'fails' ? 500 : 60_000))
                        return [500, { error: 'boom' }]
                    },
                },
            })
            await expectLogic(logic, () => logic.actions.loadSnapshotSources()).toDispatchActions([
                'loadSnapshotSourcesSuccess',
            ])

            jest.useFakeTimers({ doNotFake: ['nextTick', 'setImmediate', 'queueMicrotask'] })
            try {
                logic.actions.loadSnapshotsForSource([DIRECT_SOURCE, secondSource])
                await jest.advanceTimersByTimeAsync(35_000)
            } finally {
                jest.useRealTimers()
            }
            await expectLogic(logic).toDispatchActions([expectedAction])

            expect(snapshotsEndpointBlockReads > 0).toBe(expectsSnapshotsEndpoint)
        })
    })

    describe('isSnapshotUnauthorized', () => {
        it('is false when no error', () => {
            expect(logic.values.isSnapshotUnauthorized).toBe(false)
        })

        it('is true for a 401', () => {
            logic.actions.loadSnapshotsForSourceFailure('Unauthorized', new ApiError('Unauthorized', 401))

            expect(logic.values.isSnapshotUnauthorized).toBe(true)
        })

        it('is false for a non-401 error', () => {
            logic.actions.loadSnapshotsForSourceFailure('Forbidden', new ApiError('Forbidden', 403))

            expect(logic.values.isSnapshotUnauthorized).toBe(false)
        })
    })

    describe('snapshot parsing', () => {
        const sessionId = '12345'
        const numberOfParsedLinesInData = 8
        it('handles normal web data', async () => {
            const parsed = await parseEncodedSnapshots(encodedWebSnapshotData, sessionId)
            expect(parsed.length).toEqual(numberOfParsedLinesInData)
            expect(parsed).toMatchSnapshot()
        })

        it('handles data with unparseable lines', async () => {
            const parsed = await parseEncodedSnapshots(
                encodedWebSnapshotData.map((line, index) => {
                    return index == 0 ? line.substring(0, line.length / 2) : line
                }),
                sessionId
            )

            // unparseable lines are not returned
            expect(encodedWebSnapshotData.length).toEqual(2)
            expect(parsed.length).toEqual(numberOfParsedLinesInData / 2)

            expect(parsed).toMatchSnapshot()
        })
    })

    describe('mutation chunking', () => {
        const createMutationSnapshot = (addsCount: number): RecordingSnapshot =>
            ({
                type: EventType.IncrementalSnapshot,
                timestamp: 1000,
                data: {
                    source: IncrementalSource.Mutation,
                    adds: Array(addsCount).fill({ parentId: 1, nextId: null, node: { type: 1, tagName: 'div' } }),
                    removes: [{ parentId: 1, id: 2 }],
                    texts: [{ id: 3, value: 'text' }],
                    attributes: [{ id: 4, attributes: { class: 'test' } }],
                },
                windowId: 1,
            }) as RecordingSnapshot

        it('does not chunk snapshots with adds below chunk size', () => {
            const snapshot = createMutationSnapshot(100)
            const chunks = chunkMutationSnapshot(snapshot)
            expect(chunks).toEqual([snapshot])
        })

        it('chunks large mutation snapshots correctly', () => {
            const addsCount = MUTATION_CHUNK_SIZE * 2 + 500 // Will create 3 chunks
            const snapshot = createMutationSnapshot(addsCount)
            const chunks = chunkMutationSnapshot(snapshot)

            expect(chunks.length).toBe(3)

            // First chunk
            expect(chunks[0]).toMatchObject({
                timestamp: 1000,
                data: {
                    adds: expect.arrayContaining([expect.any(Object)]),
                    removes: (snapshot.data as mutationData).removes,
                    texts: [],
                    attributes: [],
                },
            })
            expect((chunks[0].data as mutationData).adds.length).toBe(MUTATION_CHUNK_SIZE)

            // Middle chunk
            expect(chunks[1]).toMatchObject({
                timestamp: 1000,
                data: {
                    adds: expect.arrayContaining([expect.any(Object)]),
                    removes: [],
                    texts: [],
                    attributes: [],
                },
            })
            expect((chunks[1].data as mutationData).adds.length).toBe(MUTATION_CHUNK_SIZE)

            // Last chunk
            expect(chunks[2]).toMatchObject({
                timestamp: 1000,
                data: {
                    adds: expect.arrayContaining([expect.any(Object)]),
                    removes: [],
                    texts: (snapshot.data as mutationData).texts,
                    attributes: (snapshot.data as mutationData).attributes,
                },
            })
            expect((chunks[2].data as mutationData).adds.length).toBe(500)
        })

        it('handles delay correctly when chunking', () => {
            const snapshot = createMutationSnapshot(MUTATION_CHUNK_SIZE * 2)
            snapshot.delay = 100

            const chunks = chunkMutationSnapshot(snapshot)

            expect(chunks.length).toBe(2)
            expect(chunks[0].delay).toBe(100)
            expect(chunks[1].delay).toBe(100)
        })

        it('does not chunk non-mutation snapshots', () => {
            const snapshot: RecordingSnapshot = {
                type: EventType.FullSnapshot,
                timestamp: 1000,
                data: {
                    node: { type: NodeType.Document, id: 1, childNodes: [] },
                    initialOffset: { top: 0, left: 0 },
                },
                windowId: 1,
            }
            const chunks = chunkMutationSnapshot(snapshot)
            expect(chunks).toEqual([snapshot])
        })
    })
})
