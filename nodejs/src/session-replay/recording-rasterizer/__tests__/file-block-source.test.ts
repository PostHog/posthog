import * as fs from 'fs/promises'
import * as os from 'os'
import * as path from 'path'
import { PassThrough, Readable } from 'stream'
import { pipeline } from 'stream/promises'
import { zstdCompressSync } from 'zlib'

import { FileBlockSource, isAllowedSource } from '~/session-replay/recording-rasterizer/capture/file-block-source'
import { byteLimit } from '~/session-replay/recording-rasterizer/storage'

describe('FileBlockSource', () => {
    let dir: string

    beforeEach(async () => {
        dir = await fs.mkdtemp(path.join(os.tmpdir(), 'file-block-source-'))
    })

    afterEach(async () => {
        await fs.rm(dir, { recursive: true, force: true })
    })

    async function serve(source: FileBlockSource): Promise<{ status: number; body: string }> {
        const respond = jest.fn()
        await source.handleRequest({ respond } as any, '/__blocks/0')
        const { status, body } = respond.mock.calls[0][0]
        return { status, body: Buffer.from(body).toString('utf-8') }
    }

    it.each([
        ['serves a zstd file decompressed', 1_000, 200, '["w",{"type":4}]\n'],
        // A source that inflates past the bound is refused as a failed block, not decompressed into memory.
        ['refuses one that decompresses past the bound', 8, 502, 'block read failed'],
    ])('%s', async (_name, maxDecompressedBytes, expectedStatus, expectedBody) => {
        const file = path.join(dir, 'events.jsonl.zst')
        await fs.writeFile(file, zstdCompressSync(Buffer.from('["w",{"type":4}]\n')))
        const source = new FileBlockSource(file, maxDecompressedBytes)

        await source.fetchBlocks()

        expect(await serve(source)).toEqual({ status: expectedStatus, body: expectedBody })
    })

    // The allowlist is the only thing between a render input and every object the rasterizer's role can read.
    it.each([
        ['s3://bench/rv-benchmark/v1/cases/a/events.jsonl.zst', true],
        ['s3://bench/rv-benchmark-private/v1/events.jsonl.zst', false],
        ['s3://other/rv-benchmark/v1/events.jsonl.zst', false],
        ['s3://bench/rv-benchmark/../exports/mp4/x.mp4', false],
    ])('isAllowedSource(%s) is %s under s3://bench/rv-benchmark', (uri, expected) => {
        expect(isAllowedSource(uri, ['s3://bench/rv-benchmark'])).toBe(expected)
    })

    // A source download with no Content-Length to check up front still stops at the size gate.
    it('byteLimit fails a download once it passes the limit', async () => {
        const sink = new PassThrough()
        sink.resume()

        await expect(
            pipeline(Readable.from([Buffer.alloc(6), Buffer.alloc(6)]), byteLimit(10), sink)
        ).rejects.toMatchObject({ code: 'RECORDING_TOO_LARGE' })
    })
})
