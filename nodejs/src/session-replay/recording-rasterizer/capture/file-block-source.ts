import * as fs from 'fs/promises'
import { HTTPRequest } from 'puppeteer'
import { zstdDecompressSync } from 'zlib'

import { BLOCK_REQUEST_PREFIX, BlockSource } from './block-proxy'

const ZSTD_MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd])

// Serves one recording file as block 0; `cv` payloads inside stay compressed for the player to decode.
export class FileBlockSource implements BlockSource {
    private jsonl = ''
    private fileBytes = 0

    constructor(private filePath: string) {}

    get blockCount(): number {
        return this.jsonl ? 1 : 0
    }

    get totalCompressedBytes(): number {
        return this.fileBytes
    }

    async fetchBlocks(): Promise<number> {
        const raw = await fs.readFile(this.filePath)
        this.fileBytes = raw.length
        const isZstd = raw.subarray(0, 4).equals(ZSTD_MAGIC)
        this.jsonl = (isZstd ? zstdDecompressSync(raw) : raw).toString('utf-8')
        return this.blockCount
    }

    async handleRequest(request: HTTPRequest, path: string): Promise<void> {
        if (path !== `${BLOCK_REQUEST_PREFIX}0`) {
            await request.respond({ status: 404, body: 'block not found' })
            return
        }
        await request.respond({ status: 200, contentType: 'text/plain', body: this.jsonl })
    }
}
