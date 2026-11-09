import { Counter } from 'prom-client'
import { z } from 'zod'

import { MAX_EMAIL_ATTACHMENTS } from '~/cdp/schema/cyclotron'
import { buildIntegerMatcher } from '~/common/config/matchers'
import { RedisV2 } from '~/common/redis/redis-v2'
import { logger } from '~/common/utils/logger'

import { AttachmentStore, AttachmentStoreUnavailableError, DAY_MS, SHA256_HEX, UploadSlot } from './attachment-store'
import { MESSAGE_MAX_BYTES, estimateMessageBytes } from './message-estimate'

export const ATTACHMENT_UPLOAD_QUOTA_KEY_PREFIX = 'cdp-email-attachments-upload-bytes'
const QUOTA_KEY_TTL_SECONDS = (2 * DAY_MS) / 1000
const CHARGE_SCRIPT = `
local total = tonumber(redis.call('GET', KEYS[1]) or '0') + tonumber(ARGV[1])
if total > tonumber(ARGV[2]) then
    return 0
end
redis.call('SET', KEYS[1], total, 'EX', ARGV[3])
return 1
`

const UploadsRequestSchema = z.object({
    files: z
        .array(z.object({ sha256: z.string().regex(SHA256_HEX), size: z.number().int().positive() }))
        .min(1)
        .max(MAX_EMAIL_ATTACHMENTS),
})

export type AttachmentUploadsSettings = { teams: string; maxBytesPerTeamDay: number }
export type UploadsAnswer = { status: number; body: Record<string, unknown> }

const uploadRequestsTotal = new Counter({
    name: 'cdp_email_attachments_upload_requests_total',
    help: 'Upload requests for the files of transactional emails, by outcome: answered, or the refusal code',
    labelNames: ['outcome'],
})

export function countUploadRequest(outcome: string): void {
    uploadRequestsTotal.inc({ outcome })
}

const DELIVERY_UNAVAILABLE: UploadsAnswer = { status: 503, body: { error: 'delivery_unavailable' } }

export class AttachmentUploads {
    private readonly isAllowed: (teamId: number) => boolean

    constructor(
        private readonly store: AttachmentStore | null,
        private readonly counter: RedisV2 | null,
        private readonly settings: AttachmentUploadsSettings
    ) {
        this.isAllowed = buildIntegerMatcher(settings.teams, true)
    }

    public async prepare(teamId: number, body: unknown): Promise<UploadsAnswer> {
        const answer = await this.answer(teamId, body)
        countUploadRequest(String(answer.body.error ?? 'answered'))
        return answer
    }

    private async answer(teamId: number, body: unknown): Promise<UploadsAnswer> {
        if (!this.isAllowed(teamId)) {
            return { status: 400, body: { error: 'field_not_accepted' } }
        }
        const parsed = UploadsRequestSchema.safeParse(body)
        if (!parsed.success) {
            return { status: 400, body: { error: 'invalid_request', detail: parsed.error.message } }
        }
        const files = parsed.data.files
        const sizeOf = new Map(files.map((file) => [file.sha256, file.size]))
        if (files.some((file) => sizeOf.get(file.sha256) !== file.size)) {
            return { status: 400, body: { error: 'invalid_request', detail: 'One sha256 is listed with two sizes' } }
        }
        const messageBytes = estimateMessageBytes(files.map((file) => file.size))
        if (messageBytes > MESSAGE_MAX_BYTES) {
            const largest = files.reduce((a, b) => (b.size > a.size ? b : a))
            return {
                status: 400,
                body: {
                    error: 'message_too_large',
                    sha256: largest.sha256,
                    message_bytes: messageBytes,
                    max_message_bytes: MESSAGE_MAX_BYTES,
                },
            }
        }
        if (!this.store || !this.counter) {
            return DELIVERY_UNAVAILABLE
        }

        let slots: UploadSlot[]
        try {
            slots = await this.store.prepareUploads(teamId, files)
        } catch (error) {
            if (error instanceof AttachmentStoreUnavailableError) {
                return unavailable(teamId, 'Could not prepare the upload URLs of a team', error)
            }
            throw error
        }

        const distinctHashesToUpload = new Set(
            slots.filter((slot) => slot.status === 'upload').map((slot) => slot.sha256)
        )
        const uploadBytes = [...distinctHashesToUpload].reduce((total, sha256) => total + sizeOf.get(sha256)!, 0)
        if (uploadBytes > 0) {
            let charged: boolean
            try {
                charged = await this.chargeDailyUploadBytes(this.counter, teamId, uploadBytes)
            } catch (error) {
                return unavailable(teamId, 'Could not count the upload bytes of a team', error)
            }
            if (!charged) {
                return {
                    status: 429,
                    body: { error: 'upload_quota_exceeded', max_bytes_per_day: this.settings.maxBytesPerTeamDay },
                }
            }
        }
        return { status: 200, body: { files: slots.map(toAnswer) } }
    }

    private async chargeDailyUploadBytes(counter: RedisV2, teamId: number, bytes: number): Promise<boolean> {
        const key = `${ATTACHMENT_UPLOAD_QUOTA_KEY_PREFIX}:${teamId}:${new Date().toISOString().slice(0, 10)}`
        const charged = await counter.useClient({ name: 'email-attachments-upload-quota' }, (client) =>
            client.eval(CHARGE_SCRIPT, 1, key, bytes, this.settings.maxBytesPerTeamDay, QUOTA_KEY_TTL_SECONDS)
        )
        return charged === 1
    }
}

function unavailable(teamId: number, message: string, error: unknown): UploadsAnswer {
    logger.warn('⚠️', message, { team_id: teamId, error: error instanceof Error ? error.message : String(error) })
    return DELIVERY_UNAVAILABLE
}

function toAnswer(slot: UploadSlot): Record<string, unknown> {
    if (slot.status === 'present') {
        return { sha256: slot.sha256, status: 'present', expires_at: slot.expiresAt.toISOString() }
    }
    return {
        sha256: slot.sha256,
        status: 'upload',
        url: slot.url,
        method: slot.method,
        headers: slot.headers,
        url_expires_at: slot.urlExpiresAt.toISOString(),
    }
}
