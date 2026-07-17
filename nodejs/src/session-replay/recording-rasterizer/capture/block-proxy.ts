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

        const url = `${this.cfg.recordingApiBaseUrl}/api/projects/${input.team_id}/recordings/${input.session_id}/blocks`
        const resp = await internalFetch(url, {
            headers: this.authHeaders(),
        })
        if (resp.status < 200 || resp.status >= 300) {
            const body = await resp.text()
            throw new RasterizationError(
                `Failed to fetch block listing: ${resp.status} - ${body}`,
                resp.status >= 500,
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
            const url = `${apiBase}/${this.teamId}/recordings/${this.sessionId}/block?${params}`
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
