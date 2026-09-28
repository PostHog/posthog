import * as fs from 'fs/promises'
import * as os from 'os'
import * as path from 'path'
import { zstdCompressSync } from 'zlib'

import { FileBlockSource } from '~/session-replay/recording-rasterizer/capture/file-block-source'

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
})
