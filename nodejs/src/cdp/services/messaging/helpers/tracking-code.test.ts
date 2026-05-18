import { generateEmailTrackingCode, parseEmailTrackingCode } from './tracking-code'

// Hand-encode a raw payload the same way generateEmailTrackingCode does, so we can test
// pre-fix legacy shapes (4-segment) without pulling in the generator.
const encodeRaw = (payload: string): string =>
    Buffer.from(payload, 'utf8').toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')

describe('email tracking code', () => {
    describe('parseEmailTrackingCode', () => {
        it.each([
            {
                name: 'roundtrips all invocation fields including parentRunId',
                encoded: generateEmailTrackingCode({
                    functionId: 'fn-1',
                    id: 'inv-2',
                    teamId: 3,
                    parentRunId: 'batch-4',
                    state: { actionId: 'act-5' },
                }),
                expected: {
                    functionId: 'fn-1',
                    invocationId: 'inv-2',
                    teamId: '3',
                    actionId: 'act-5',
                    parentRunId: 'batch-4',
                },
            },
            {
                name: 'omits parentRunId when not supplied',
                encoded: generateEmailTrackingCode({
                    functionId: 'fn-1',
                    id: 'inv-2',
                    teamId: 3,
                    state: { actionId: 'act-5' },
                }),
                expected: {
                    functionId: 'fn-1',
                    invocationId: 'inv-2',
                    teamId: '3',
                    actionId: 'act-5',
                    parentRunId: undefined,
                },
            },
            {
                // Webhooks for emails already in flight when the fix deploys must still parse.
                name: 'parses legacy 4-segment codes emitted before parentRunId existed',
                encoded: encodeRaw('fn-1:inv-2:3:act-5'),
                expected: {
                    functionId: 'fn-1',
                    invocationId: 'inv-2',
                    teamId: '3',
                    actionId: 'act-5',
                    parentRunId: undefined,
                },
            },
            {
                name: 'returns null when the encoded string is empty',
                encoded: '',
                expected: null,
            },
        ])('$name', ({ encoded, expected }) => {
            expect(parseEmailTrackingCode(encoded)).toEqual(expected)
        })
    })
})
