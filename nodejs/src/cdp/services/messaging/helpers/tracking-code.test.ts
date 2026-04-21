import { generateEmailTrackingCode, parseEmailTrackingCode } from './tracking-code'

describe('email tracking code', () => {
    it('roundtrips all invocation fields including parentRunId', () => {
        const encoded = generateEmailTrackingCode({
            functionId: 'fn-1',
            id: 'inv-2',
            teamId: 3,
            parentRunId: 'batch-4',
            state: { actionId: 'act-5' },
        })

        expect(parseEmailTrackingCode(encoded)).toEqual({
            functionId: 'fn-1',
            invocationId: 'inv-2',
            teamId: '3',
            actionId: 'act-5',
            parentRunId: 'batch-4',
        })
    })

    it('omits parentRunId when not supplied', () => {
        const encoded = generateEmailTrackingCode({
            functionId: 'fn-1',
            id: 'inv-2',
            teamId: 3,
            state: { actionId: 'act-5' },
        })

        expect(parseEmailTrackingCode(encoded)).toEqual({
            functionId: 'fn-1',
            invocationId: 'inv-2',
            teamId: '3',
            actionId: 'act-5',
            parentRunId: undefined,
        })
    })

    it('parses legacy 4-segment codes emitted before parentRunId existed', () => {
        // Hand-encoded "fn-1:inv-2:3:act-5" — the pre-fix format. Webhooks for emails
        // already in flight when the fix deploys must still parse cleanly.
        const legacy = Buffer.from('fn-1:inv-2:3:act-5', 'utf8')
            .toString('base64')
            .replace(/\+/g, '-')
            .replace(/\//g, '_')
            .replace(/=+$/, '')

        expect(parseEmailTrackingCode(legacy)).toEqual({
            functionId: 'fn-1',
            invocationId: 'inv-2',
            teamId: '3',
            actionId: 'act-5',
            parentRunId: undefined,
        })
    })

    it('returns null when functionId or invocationId are missing', () => {
        expect(parseEmailTrackingCode('')).toBeNull()
    })
})
