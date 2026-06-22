import { classifySlackError } from './slack-errors'

describe('classifySlackError', () => {
    // The Hog VM stringifies the parsed response body as a dict with single-quoted keys.
    const hogDictMessage = (code: string): string =>
        `Failed to post message to Slack: 200: {'ok': false, 'error': '${code}'}`

    it.each([
        'not_in_channel',
        'channel_not_found',
        'account_inactive',
        'is_archived',
        'invalid_auth',
        'token_revoked',
        'restricted_action',
        'org_login_required',
    ])('classifies %s as terminal', (code) => {
        expect(classifySlackError(hogDictMessage(code))).toEqual({ code, kind: 'terminal' })
    })

    it.each(['ratelimited', 'rate_limited'])('classifies %s as transient', (code) => {
        expect(classifySlackError(hogDictMessage(code))).toEqual({ code, kind: 'transient' })
    })

    it('matches double-quoted (raw JSON) bodies when the body did not parse', () => {
        expect(
            classifySlackError('Failed to post message to Slack: 200: {"ok":false,"error":"not_in_channel"}')
        ).toEqual({ code: 'not_in_channel', kind: 'terminal' })
    })

    it('returns null for unknown Slack error codes (keeps existing fail behavior)', () => {
        expect(classifySlackError(hogDictMessage('some_new_error'))).toBeNull()
    })

    it('returns null for non-Slack errors', () => {
        expect(classifySlackError("raise Exception('fail!')")).toBeNull()
        expect(classifySlackError('Total variable size exceeds 5KB limit')).toBeNull()
    })

    it('returns null for empty / missing messages', () => {
        expect(classifySlackError(undefined)).toBeNull()
        expect(classifySlackError(null)).toBeNull()
        expect(classifySlackError('')).toBeNull()
    })

    it('does not classify a known code that lacks the Slack failure signature', () => {
        // Guard against misclassifying an unrelated error that happens to mention a code.
        expect(classifySlackError("{'error': 'not_in_channel'}")).toBeNull()
    })
})
