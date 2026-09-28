import * as fs from 'fs/promises'
import { HTTPRequest } from 'puppeteer'
import { zstdDecompressSync } from 'zlib'

import { RasterizationError } from '~/session-replay/recording-rasterizer/errors'
import { downloadFromS3, parseS3Uri } from '~/session-replay/recording-rasterizer/storage'

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

// The rasterizer's role can read every team's exports, so the allowlist bounds what a source can point at.
export async function blockSourceFromS3(
    uri: string,
    localPath: string,
    allowedPrefixes: string[]
): Promise<FileBlockSource> {
    if (!allowedPrefixes.some((prefix) => uri.startsWith(prefix))) {
        throw new RasterizationError(`source_s3_uri is outside the allowed prefixes: ${uri}`, false, 'INVALID_INPUT')
    }
    const { bucket, key } = parseS3Uri(uri)
    await downloadFromS3(bucket, key, localPath)
    return new FileBlockSource(localPath)
}
