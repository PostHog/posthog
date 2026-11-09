import { Counter } from 'prom-client'
import { z } from 'zod'

import { buildIntegerMatcher } from '~/common/config/matchers'
import { RedisV2 } from '~/common/redis/redis-v2'
import { logger } from '~/common/utils/logger'

import { AttachmentStore, AttachmentStoreUnavailableError, UploadSlot } from './attachment-store'
import { MESSAGE_MAX_BYTES, estimateMessageBytes } from './message-estimate'

export const ATTACHMENT_UPLOAD_QUOTA_KEY_PREFIX = 'cdp-email-attachments-upload-bytes'
// A day's counter outlives its UTC day, so a request just after midnight still reads the right one.
const QUOTA_KEY_TTL_SECONDS = 2 * 24 * 60 * 60

// Unknown keys are dropped rather than refused, so Django can add a field before every cdp-api pod reads it.
const UploadsRequestSchema = z.object({
    files: z
        .array(z.object({ sha256: z.string().regex(/^[0-9a-f]{64}$/), size: z.number().int().positive() }))
        .min(1)
        .max(10),
})

export type AttachmentUploadsSettings = { teams: string; maxBytesPerTeamDay: number }
export type UploadsAnswer = { status: number; body: Record<string, unknown> }

const uploadRequestsTotal = new Counter({
    name: 'cdp_email_attachments_upload_requests_total',
    help: 'Upload requests for the files of transactional emails, by outcome: answered, or the refusal code',
    labelNames: ['outcome'],
})

const DELIVERY_UNAVAILABLE: UploadsAnswer = { status: 503, body: { error: 'delivery_unavailable' } }

export class AttachmentUploads {
    private readonly isAllowed: (teamId: number) => boolean

    constructor(
        private readonly store: AttachmentStore | null,
        private readonly redis: RedisV2,
        private readonly settings: AttachmentUploadsSettings,
        private readonly now: () => Date = () => new Date()
    ) {
        this.isAllowed = buildIntegerMatcher(settings.teams, true)
    }

    public async prepare(teamId: number, body: unknown): Promise<UploadsAnswer> {
        const answer = await this.answer(teamId, body)
        uploadRequestsTotal.inc({ outcome: String(answer.body.error ?? 'answered') })
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
        if (!this.store) {
            return DELIVERY_UNAVAILABLE
        }

        let slots: UploadSlot[]
        try {
            slots = await this.store.prepareUploads(teamId, files)
        } catch (error) {
            if (error instanceof AttachmentStoreUnavailableError) {
                return DELIVERY_UNAVAILABLE
            }
            throw error
        }

        // A file named twice in one request is uploaded once.
        const sizeOf = new Map(files.map((file) => [file.sha256, file.size]))
        const toUpload = new Set(slots.filter((slot) => slot.status === 'upload').map((slot) => slot.sha256))
        const uploadBytes = [...toUpload].reduce((total, sha256) => total + sizeOf.get(sha256)!, 0)
        if (uploadBytes > 0) {
            let charged: boolean
            try {
                charged = await this.charge(teamId, uploadBytes)
            } catch (error) {
                logger.warn('⚠️', 'Could not count the upload bytes of a team', {
                    team_id: teamId,
                    error: error instanceof Error ? error.message : String(error),
                })
                return DELIVERY_UNAVAILABLE
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

    // Counts the bytes of the upload slots a team gets per UTC day. A refused request gives its bytes back, so it
    // does not use up the rest of the team's day.
    private async charge(teamId: number, bytes: number): Promise<boolean> {
        const key = `${ATTACHMENT_UPLOAD_QUOTA_KEY_PREFIX}:${teamId}:${this.now().toISOString().slice(0, 10)}`
        const charged = await this.redis.useClient({ name: 'email-attachments-upload-quota' }, async (client) => {
            const total = await client.incrby(key, bytes)
            await client.expire(key, QUOTA_KEY_TTL_SECONDS)
            if (total <= this.settings.maxBytesPerTeamDay) {
                return true
            }
            await client.decrby(key, bytes)
            return false
        })
        return charged === true
    }
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
