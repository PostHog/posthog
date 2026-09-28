import * as fs from 'fs/promises'
import { HTTPRequest } from 'puppeteer'
import { promisify } from 'util'
import { zstdDecompress } from 'zlib'

import { RasterizationError } from '~/session-replay/recording-rasterizer/errors'
import { downloadFromS3, parseS3Uri } from '~/session-replay/recording-rasterizer/storage'

import { BLOCK_REQUEST_PREFIX, BlockSource } from './block-proxy'

const ZSTD_MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd])
const zstdDecompressAsync = promisify(zstdDecompress)

// Serves one recording file as block 0; `cv` payloads inside stay compressed for the player to decode.
export class FileBlockSource implements BlockSource {
    private fileBytes: number | null = null

    constructor(
        private filePath: string,
        private maxDecompressedBytes: number
    ) {}

    get blockCount(): number {
        return this.fileBytes === null ? 0 : 1
    }

    get totalCompressedBytes(): number {
        return this.fileBytes ?? 0
    }

    // Size only: the recorder's size gate runs on it before anything is read or decompressed.
    async fetchBlocks(): Promise<number> {
        this.fileBytes = (await fs.stat(this.filePath)).size
        return this.blockCount
    }

    async handleRequest(request: HTTPRequest, path: string): Promise<void> {
        if (path !== `${BLOCK_REQUEST_PREFIX}0` || this.fileBytes === null) {
            await request.respond({ status: 404, body: 'block not found' })
            return
        }
        let body: Buffer
        try {
            const raw = await fs.readFile(this.filePath)
            body = raw.subarray(0, 4).equals(ZSTD_MAGIC)
                ? await zstdDecompressAsync(raw, { maxOutputLength: this.maxDecompressedBytes })
                : raw
        } catch {
            await request.respond({ status: 502, body: 'block read failed' })
            return
        }
        await request.respond({ status: 200, contentType: 'text/plain', body })
    }
}

export interface SourceLimits {
    allowedPrefixes: string[]
    maxCompressedBytes: number
    maxDecompressedBytes: number
    signal?: AbortSignal
}

// The rasterizer's role can read every team's exports, so the allowlist bounds what a source can point at.
export async function blockSourceFromS3(
    uri: string,
    localPath: string,
    limits: SourceLimits
): Promise<FileBlockSource> {
    if (!limits.allowedPrefixes.some((prefix) => uri.startsWith(prefix))) {
        throw new RasterizationError(`source_s3_uri is outside the allowed prefixes: ${uri}`, false, 'INVALID_INPUT')
    }
    const { bucket, key } = parseS3Uri(uri)
    await downloadFromS3(bucket, key, localPath, { maxBytes: limits.maxCompressedBytes, signal: limits.signal })
    return new FileBlockSource(localPath, limits.maxDecompressedBytes)
}
