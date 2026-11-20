import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import {
    parseExportedSessionRecording,
    parseRawExportedSessionRecording,
    sessionRecordingFilePlaybackSceneLogic,
} from './sessionRecordingFilePlaybackSceneLogic'

jest.mock('../player/snapshot-processing/DecompressionWorkerManager')

const encodeRawExport = (
    blocks: (string | Uint8Array)[],
    headerOverrides: Record<string, unknown> = {}
): Uint8Array => {
    const encoder = new TextEncoder()
    const header = {
        version: '2026-11-raw',
        session_id: 'session-1',
        person: null,
        viewports: [{ timestamp: 1000, width: '1280', height: '720', href: 'https://example.com' }],
        block_count: blocks.length,
        ...headerOverrides,
    }
    const parts = [encoder.encode('PHREC1\n' + JSON.stringify(header) + '\n')]
    for (const block of blocks) {
        // The mocked decompressor returns its input, so each block is its decompressed JSONL text.
        const body = typeof block === 'string' ? encoder.encode(block) : block
        const prefix = new Uint8Array(4)
        new DataView(prefix.buffer).setUint32(0, body.byteLength)
        parts.push(prefix, body)
    }
    const bytes = new Uint8Array(parts.reduce((total, part) => total + part.byteLength, 0))
    let offset = 0
    for (const part of parts) {
        bytes.set(part, offset)
        offset += part.byteLength
    }
    return bytes
}

const rawBlock = (index: number, windowId = 'window-a'): string =>
    JSON.stringify([windowId, { type: 3, data: {}, timestamp: 1000 + index }])

describe('sessionRecordingFilePlaybackLogic', () => {
    let logic: ReturnType<typeof sessionRecordingFilePlaybackSceneLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    describe('file-playback logic', () => {
        beforeEach(() => {
            logic = sessionRecordingFilePlaybackSceneLogic()
            logic.mount()
        })

        it('should generate a new playerKey on load', () => {
            expectLogic(logic).toMatchValues({
                playerProps: {
                    sessionRecordingId: '',
                    playerKey: 'file-playback-empty',
                },
            })

            logic.actions.loadFromFileSuccess({} as any)
            const playerProps = logic.values.playerProps
            expect(playerProps.playerKey).toMatch(/^file-playback-.{36}$/)

            logic.actions.loadFromFileSuccess({} as any)
            expect(playerProps.playerKey).not.toEqual(logic.values.playerProps.playerKey)
        })
    })

    describe('parseExportedSessionRecording', () => {
        it.each([
            [
                '2022-12-02',
                {
                    snapshotsByWindowId: {
                        'window-a': [
                            { type: 2, data: {}, timestamp: 1000 },
                            { type: 3, data: {}, timestamp: 3000 },
                        ],
                        'window-b': [{ type: 2, data: {}, timestamp: 2000 }],
                    },
                },
            ],
            [
                '2023-04-28',
                {
                    id: '',
                    snapshots: [
                        { type: 2, data: {}, timestamp: 1000, windowId: 'window-a' },
                        { type: 2, data: {}, timestamp: 2000, windowId: 'window-b' },
                        { type: 3, data: {}, timestamp: 3000, windowId: 'window-a' },
                    ],
                },
            ],
        ])('maps window UUIDs in a %s export to integer window ids', (version, data) => {
            const parsed = parseExportedSessionRecording(JSON.stringify({ version, data }))

            expect(parsed.data.snapshots.map((s) => [s.timestamp, s.windowId])).toEqual([
                [1000, 1],
                [2000, 2],
                [3000, 1],
            ])
        })
    })

    describe('parseRawExportedSessionRecording', () => {
        it('parses every block with integer window ids and returns the header viewports', async () => {
            const windows = ['window-a', 'window-b', 'window-a']

            const parsed = await parseRawExportedSessionRecording(
                encodeRawExport(windows.map((windowId, i) => rawBlock(i, windowId)))
            )

            expect(parsed.id).toEqual('session-1')
            expect(parsed.snapshots.map((s) => [s.timestamp, s.windowId])).toEqual([
                [1000, 1],
                [1001, 2],
                [1002, 1],
            ])
            expect(parsed.viewports).toEqual([
                { timestamp: 1000, width: '1280', height: '720', href: 'https://example.com' },
            ])
        })

        it('reports unreadable lines without sending them to analytics', async () => {
            const onUnreadableLines = jest.fn()
            const captureSpy = jest.spyOn(posthog, 'capture')

            const parsed = await parseRawExportedSessionRecording(
                encodeRawExport([rawBlock(0), 'not json']),
                onUnreadableLines
            )

            expect(parsed.snapshots).toHaveLength(1)
            expect(onUnreadableLines).toHaveBeenCalled()
            expect(captureSpy).not.toHaveBeenCalled()
        })

        it.each([
            ['a truncated block', encodeRawExport([rawBlock(0), rawBlock(1)]).slice(0, -5), 'File is truncated'],
            ['a block count mismatch', encodeRawExport([rawBlock(0)], { block_count: 2 }), 'header lists 2'],
            ['an unknown version', encodeRawExport([rawBlock(0)], { version: '2099-01-raw' }), 'Unsupported'],
            ['viewports that are not a list', encodeRawExport([rawBlock(0)], { viewports: {} }), 'valid header'],
            [
                'a viewport without a timestamp',
                encodeRawExport([rawBlock(0)], { viewports: [{ width: '1', height: '1' }] }),
                'valid header',
            ],
            [
                'a viewport with a non-numeric width',
                encodeRawExport([rawBlock(0)], {
                    viewports: [{ timestamp: 1, width: 'x', height: '1', href: 'https://example.com' }],
                }),
                'valid header',
            ],
            ['a missing block count', encodeRawExport([rawBlock(0)], { block_count: undefined }), 'valid header'],
            ['an empty block', encodeRawExport(['']), 'empty block'],
            [
                'a block that would expand past the limit',
                // The varint says 4 GiB.
                encodeRawExport([new Uint8Array([0xff, 0xff, 0xff, 0xff, 0x0f, 0x00])]),
                'too large',
            ],
            [
                'too many viewports',
                encodeRawExport([rawBlock(0)], {
                    viewports: Array.from({ length: 200_001 }, () => ({
                        timestamp: 1,
                        width: '1',
                        height: '1',
                        href: '',
                    })),
                }),
                'valid header',
            ],
        ])('rejects %s', async (_, bytes, message) => {
            await expect(parseRawExportedSessionRecording(bytes)).rejects.toThrow(message)
        })
    })
})
