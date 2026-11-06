import { SmtpReply, replyForSendApiError } from './smtp-replies'

describe('replyForSendApiError', () => {
    it.each([
        [{ status: 400, code: 'sender_not_verified', detail: 'No verified sender.' }, 550],
        [{ status: 400, code: 'invalid_request', attr: 'to', detail: 'Enter an address.' }, 553],
        [{ status: 400, code: 'invalid_request', attr: 'cc__0', detail: 'Enter an address.' }, 553],
        [{ status: 400, code: 'invalid_request', attr: 'attachments__0__filename', detail: 'Blocked.' }, 554],
        [{ status: 400, code: 'invalid_request', attr: 'attachments', detail: 'Send at most 10 MB.' }, 552],
        [{ status: 413 }, 552],
        [{ status: 422, code: 'recipient_suppressed' }, 550],
        [{ status: 422, code: 'recipient_unreachable' }, 550],
        [{ status: 422, code: 'sending_suspended' }, 554],
        [{ status: 422, code: 'idempotency_key_reused' }, 554],
        [{ status: 401 }, 535],
        [{ status: 404 }, 550],
        // A client retries a 4xx unchanged, so only what a retry can fix may be temporary.
        [{ status: 409 }, 451],
        [{ status: 429, code: 'throttled' }, 451],
        [{ status: 429, code: 'quota_limited' }, 451],
        [{ status: 503 }, 451],
        [{ status: 500 }, 451],
    ])('answers %j with a %i', (error, code) => {
        const reply = replyForSendApiError(error)

        expect(reply.responseCode).toEqual(code)
        expect(reply.message).toMatch(/^[245]\.\d\.\d \S/)
    })

    it('keeps a reply to one line of ASCII that fits the limit', () => {
        const reply = new SmtpReply(550, `5.6.0 line one\r\nline two é ${'x'.repeat(500)}`)

        expect(reply.message).toMatch(/^5\.6\.0 line one line two \? x+\.\.\.$/)
        expect(reply.message.length).toBeLessThanOrEqual(400)
    })
})
