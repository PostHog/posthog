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
        try {
            const raw = await fs.readFile(this.filePath)
            const body = raw.subarray(0, 4).equals(ZSTD_MAGIC)
                ? await zstdDecompressAsync(raw, { maxOutputLength: this.maxDecompressedBytes })
                : raw
            await request.respond({ status: 200, contentType: 'text/plain', body })
        } catch {
            // A failed block is what the player reports, rather than a render left waiting on a response.
            try {
                await request.respond({ status: 502, body: 'block read failed' })
            } catch {
                // The page is already gone; nothing is left to tell.
            }
        }
    }
}

export interface SourceLimits {
    allowedPrefixes: string[]
    maxCompressedBytes: number
    maxDecompressedBytes: number
    signal?: AbortSignal
}

const S3_URI = /^s3:\/\/([^/]+)\/?(.*)$/

/**
 * Whether the object sits under one of the allowed `s3://bucket/prefix` locations. Compared as a bucket plus a
 * whole key prefix, so `s3://b/bench` does not also admit `s3://b/bench-other/`, and a `..` segment is refused.
 */
export function isAllowedSource(uri: string, allowedPrefixes: string[]): boolean {
    const source = S3_URI.exec(uri)
    if (!source || !source[2] || source[2].split('/').includes('..')) {
        return false
    }
    return allowedPrefixes.some((prefix) => {
        const allowed = S3_URI.exec(prefix)
        if (!allowed || allowed[1] !== source[1]) {
            return false
        }
        const allowedKey = allowed[2] && !allowed[2].endsWith('/') ? `${allowed[2]}/` : allowed[2]
        return source[2].startsWith(allowedKey)
    })
}

// The rasterizer's role can read every team's exports, so the allowlist bounds what a source can point at.
export async function blockSourceFromS3(
    uri: string,
    localPath: string,
    limits: SourceLimits
): Promise<FileBlockSource> {
    if (!isAllowedSource(uri, limits.allowedPrefixes)) {
        throw new RasterizationError(`source_s3_uri is outside the allowed prefixes: ${uri}`, false, 'INVALID_INPUT')
    }
    const { bucket, key } = parseS3Uri(uri)
    await downloadFromS3(bucket, key, localPath, { maxBytes: limits.maxCompressedBytes, signal: limits.signal })
    return new FileBlockSource(localPath, limits.maxDecompressedBytes)
}
