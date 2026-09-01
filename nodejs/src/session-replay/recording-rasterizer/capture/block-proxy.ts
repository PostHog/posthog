import { HTTPRequest } from 'puppeteer'

import { BLOCK_REQUEST_PREFIX } from '@posthog/replay-headless/protocol'

import { internalFetch } from '~/common/utils/request'
import { type RecordingBlock as FullRecordingBlock } from '~/session-replay/recording-api/types'
import { RasterizationError } from '~/session-replay/recording-rasterizer/errors'
import { type Logger, createLogger } from '~/session-replay/recording-rasterizer/logger'
import { RasterizeRecordingInput } from '~/session-replay/recording-rasterizer/types'

type RecordingBlock = Pick<FullRecordingBlock, 'key' | 'start_byte' | 'end_byte'>

export { BLOCK_REQUEST_PREFIX }

export class BlockProxy {
    private blocks: RecordingBlock[] = []
    private teamId = 0
    private sessionId = ''
    private recordingApiToken = ''

    constructor(
        private cfg: { recordingApiBaseUrl: string; recordingApiSecret: string },
        private log: Logger = createLogger()
    ) {}

    get blockCount(): number {
        return this.blocks.length
    }

    // Compressed bytes the render will download, known before anything loads into the browser.
    // S3 Range bytes=start-end is inclusive, so each block spans end - start + 1 bytes.
    get totalCompressedBytes(): number {
        return this.blocks.reduce((sum, block) => sum + (block.end_byte - block.start_byte + 1), 0)
    }

    // Send both the legacy shared secret (when configured) and the relayed team-scoped JWT (when one
    // was minted upstream), so recording-api accepts either and rollout stays order-independent.
    private authHeaders(): Record<string, string> {
        const headers: Record<string, string> = {}
        if (this.cfg.recordingApiSecret) {
            headers['X-Internal-Api-Secret'] = this.cfg.recordingApiSecret
        }
        if (this.recordingApiToken) {
            headers['Authorization'] = `Bearer ${this.recordingApiToken}`
        }
        return headers
    }

    async fetchBlocks(input: RasterizeRecordingInput): Promise<number> {
        this.teamId = input.team_id
        this.sessionId = input.session_id
        this.recordingApiToken = input.recording_api_token ?? ''

        // Encoded: the fetch client normalizes the URL, so a raw session id containing `../`
        // would repoint the request at another team's recording.
        const url = `${this.cfg.recordingApiBaseUrl}/api/projects/${input.team_id}/recordings/${encodeURIComponent(
            input.session_id
        )}/blocks`
        let resp
        try {
            resp = await internalFetch(url, {
                headers: this.authHeaders(),
            })
        } catch (err) {
            // Connection-level failures (recording-api rollout, DNS blip) would otherwise surface as
            // UNKNOWN; they are the most retryable failure this call has.
            throw new RasterizationError(
                `Failed to fetch block listing: ${(err as Error)?.message ?? String(err)}`,
                true,
                'BLOCK_LISTING_FAILED',
                err
            )
        }
        if (resp.status < 200 || resp.status >= 300) {
            const body = await resp.text()
            // 404 stays retryable because a recording still being ingested has no blocks yet, the
            // same race the player's NO_SNAPSHOTS handling deliberately keeps retryable. 408/429
            // are transient by definition. Remaining 4xx (auth, bad request) cannot heal on retry.
            const retryable = resp.status >= 500 || [404, 408, 429].includes(resp.status)
            throw new RasterizationError(
                `Failed to fetch block listing: ${resp.status} - ${body}`,
                retryable,
                'BLOCK_LISTING_FAILED'
            )
        }
        const data = await resp.json()
        if (!Array.isArray(data.blocks)) {
            throw new RasterizationError(
                `Invalid block listing response: expected blocks array, got ${typeof data.blocks}`,
                false,
                'BLOCK_LISTING_FAILED'
            )
        }
        this.blocks = data.blocks as RecordingBlock[]
        return this.blocks.length
    }

    async handleRequest(request: HTTPRequest, path: string): Promise<void> {
        try {
            const index = parseInt(path.slice(BLOCK_REQUEST_PREFIX.length), 10)
            if (isNaN(index) || index < 0 || index >= this.blocks.length) {
                this.log.warn({ path, index, blockCount: this.blocks.length }, 'block not found')
                await request.respond({ status: 404, body: 'block not found' })
                return
            }
            const block = this.blocks[index]
            const params = new URLSearchParams({
                key: block.key,
                start_byte: String(block.start_byte),
                end_byte: String(block.end_byte),
                decompress: 'true',
            })
            const apiBase = `${this.cfg.recordingApiBaseUrl}/api/projects`
            const url = `${apiBase}/${this.teamId}/recordings/${encodeURIComponent(this.sessionId)}/block?${params}`
            const resp = await internalFetch(url, {
                headers: this.authHeaders(),
            })
            if (resp.status < 200 || resp.status >= 300) {
                const text = await resp.text()
                this.log.warn({ index, status: resp.status, body: text }, 'upstream block fetch failed')
                await request.respond({ status: resp.status, body: text })
                return
            }
            const contentType = resp.headers['content-type'] || 'application/octet-stream'
            await request.respond({
                status: resp.status,
                contentType,
                body: await resp.text(),
            })
        } catch (err) {
            this.log.error({ path, err }, 'block proxy failed')
            try {
                await request.respond({ status: 502, body: 'block proxy error' })
            } catch (respondErr) {
                this.log.debug({ path, respondErr }, 'could not send 502 response, page likely closed')
            }
        }
    }
}
