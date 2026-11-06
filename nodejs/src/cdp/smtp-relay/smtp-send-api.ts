import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { internalFetch } from '~/common/utils/request'

import type { SmtpSend } from './smtp-message'
import { REPLIES, replyForSendApiError } from './smtp-replies'

export type SmtpCredential = { apiKey: string; teamId: number }

export type SmtpActivity = {
    kind: 'refused' | 'dropped_headers'
    reply?: string
    from?: string
    to?: string[]
    message_id?: string
    dropped_headers?: string[]
}

const AUTH_TIMEOUT_MS = 3_000
const ACTIVITY_TIMEOUT_MS = 3_000

const responseJson = (text: string): Record<string, any> => {
    try {
        const parsed = parseJSON(text)
        return parsed && typeof parsed === 'object' ? parsed : {}
    } catch {
        return {}
    }
}

/** The relay's only way into PostHog: the same API a customer's code calls, with the customer's own key. */
export class SmtpSendApi {
    constructor(private readonly apiUrl: string) {}

    public async checkKey(apiKey: string): Promise<SmtpCredential> {
        let response
        try {
            response = await internalFetch(`${this.apiUrl}/api/projects/@current/messaging/send/smtp_check/`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
                body: '{}',
                timeoutMs: AUTH_TIMEOUT_MS,
            })
        } catch {
            throw REPLIES.authUnavailable()
        }
        const body = responseJson(await response.text())
        if (response.status === 200 && typeof body.team_id === 'number') {
            return { apiKey, teamId: body.team_id }
        }
        if (response.status === 401) {
            throw REPLIES.invalidCredentials()
        }
        if (response.status === 403) {
            throw REPLIES.missingScope()
        }
        if (response.status === 404) {
            throw REPLIES.notEnabled()
        }
        throw REPLIES.authUnavailable()
    }

    /** Resolves to the queued message's ID. Throws the reply the client should get. */
    public async send(credential: SmtpCredential, send: SmtpSend, timeoutMs: number): Promise<string> {
        let response
        try {
            response = await internalFetch(`${this.apiUrl}/api/projects/${credential.teamId}/messaging/send/email/`, {
                method: 'POST',
                headers: {
                    Authorization: `Bearer ${credential.apiKey}`,
                    'Content-Type': 'application/json',
                    'X-PostHog-Send-Source': 'smtp',
                    ...(send.idempotencyKey && { 'Idempotency-Key': send.idempotencyKey }),
                },
                body: JSON.stringify(send.body),
                timeoutMs,
            })
        } catch {
            throw REPLIES.unconfirmed()
        }
        const body = responseJson(await response.text())
        if (response.status === 202) {
            return String(body.message_id)
        }
        throw replyForSendApiError({
            status: response.status,
            code: typeof body.code === 'string' ? body.code : undefined,
            detail: typeof body.detail === 'string' ? body.detail : undefined,
            attr: typeof body.attr === 'string' ? body.attr : undefined,
        })
    }

    /** Best effort, so that a failure here never changes what the client is told. */
    public async recordActivity(credential: SmtpCredential, activity: SmtpActivity): Promise<void> {
        try {
            await internalFetch(`${this.apiUrl}/api/projects/${credential.teamId}/messaging/send/smtp_activity/`, {
                method: 'POST',
                headers: { Authorization: `Bearer ${credential.apiKey}`, 'Content-Type': 'application/json' },
                body: JSON.stringify(activity),
                timeoutMs: ACTIVITY_TIMEOUT_MS,
            })
        } catch (error) {
            logger.warn('⚠️', 'SMTP relay could not record activity', {
                team_id: credential.teamId,
                error: error instanceof Error ? error.message : String(error),
            })
        }
    }
}
