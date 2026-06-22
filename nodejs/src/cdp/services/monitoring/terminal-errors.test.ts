import { detectTerminalError } from './terminal-errors'

describe('detectTerminalError', () => {
    const slackUrl = 'https://slack.com/api/chat.postMessage'

    it.each([
        'not_in_channel',
        'account_inactive',
        'is_archived',
        'channel_not_found',
        'invalid_auth',
        'token_revoked',
    ])('detects terminal Slack error %s', (error) => {
        const result = detectTerminalError({ status: 200, body: { ok: false, error } }, slackUrl)
        expect(result).toEqual({ reason: `slack:${error}`, message: expect.any(String) })
    })

    it('ignores transient/unknown Slack errors', () => {
        expect(detectTerminalError({ status: 200, body: { ok: false, error: 'rate_limited' } }, slackUrl)).toBeNull()
        expect(detectTerminalError({ status: 200, body: { ok: false, error: 'internal_error' } }, slackUrl)).toBeNull()
    })

    it('ignores successful Slack responses', () => {
        expect(detectTerminalError({ status: 200, body: { ok: true } }, slackUrl)).toBeNull()
    })

    it('ignores non-Slack URLs even with a matching error code', () => {
        const result = detectTerminalError(
            { status: 200, body: { ok: false, error: 'not_in_channel' } },
            'https://example.com/api/post'
        )
        expect(result).toBeNull()
    })

    it('handles non-object and missing bodies safely', () => {
        expect(detectTerminalError({ status: 200, body: 'plain text' }, slackUrl)).toBeNull()
        expect(detectTerminalError({ status: 200, body: null }, slackUrl)).toBeNull()
        expect(detectTerminalError({ status: 200, body: undefined }, slackUrl)).toBeNull()
    })

    it('requires ok === false (not merely falsy)', () => {
        expect(detectTerminalError({ status: 200, body: { error: 'not_in_channel' } }, slackUrl)).toBeNull()
    })
})
