import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    parseExportedSessionRecording,
    parseRawExportedSessionRecording,
    sessionRecordingFilePlaybackSceneLogic,
} from './sessionRecordingFilePlaybackSceneLogic'

jest.mock('../player/snapshot-processing/DecompressionWorkerManager')

const encodeRawExport = (blocks: string[], headerOverrides: Record<string, unknown> = {}): Uint8Array => {
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
        const body = encoder.encode(block)
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
        it('keeps window ids stable across parse groups and returns the header viewports', async () => {
            const blocks = Array.from({ length: 120 }, (_, i) =>
                rawBlock(i, i >= 50 && i % 2 === 0 ? 'window-b' : 'window-a')
            )

            const parsed = await parseRawExportedSessionRecording(encodeRawExport(blocks))

            expect(parsed.id).toEqual('session-1')
            expect(parsed.snapshots).toHaveLength(120)
            const windowB = (s: { timestamp: number }): boolean => s.timestamp >= 1050 && s.timestamp % 2 === 0
            expect(new Set(parsed.snapshots.filter((s) => !windowB(s)).map((s) => s.windowId))).toEqual(new Set([1]))
            expect(new Set(parsed.snapshots.filter(windowB).map((s) => s.windowId))).toEqual(new Set([2]))
            expect(parsed.viewports).toEqual([
                { timestamp: 1000, width: '1280', height: '720', href: 'https://example.com' },
            ])
        })

        it.each([
            ['a truncated block', encodeRawExport([rawBlock(0), rawBlock(1)]).slice(0, -5), 'File is truncated'],
            ['a block count mismatch', encodeRawExport([rawBlock(0)], { block_count: 2 }), 'header lists 2'],
            ['an unknown version', encodeRawExport([rawBlock(0)], { version: '2099-01-raw' }), 'Unsupported'],
        ])('rejects %s', async (_, bytes, message) => {
            await expect(parseRawExportedSessionRecording(bytes)).rejects.toThrow(message)
        })
    })
})
