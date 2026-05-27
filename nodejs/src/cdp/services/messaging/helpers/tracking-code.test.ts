import { generateEmailTrackingCode, parseEmailTrackingCode } from './tracking-code'

// Hand-encode a raw payload the same way generateEmailTrackingCode does, so we can test
// pre-fix legacy shapes without pulling in the generator.
const encodeRaw = (payload: string): string =>
    Buffer.from(payload, 'utf8').toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')

describe('email tracking code', () => {
    describe('parseEmailTrackingCode', () => {
        it.each([
            {
                name: 'roundtrips all invocation fields including distinctId',
                encoded: generateEmailTrackingCode({
                    functionId: 'fn-1',
                    id: 'inv-2',
                    teamId: 3,
                    parentRunId: 'batch-4',
                    state: { actionId: 'act-5' },
                    distinctId: 'user@example.com',
                }),
                expected: {
                    functionId: 'fn-1',
                    invocationId: 'inv-2',
                    teamId: '3',
                    actionId: 'act-5',
                    parentRunId: 'batch-4',
                    distinctId: 'user@example.com',
                },
            },
            {
                name: 'roundtrips with UUID distinctId',
                encoded: generateEmailTrackingCode({
                    functionId: 'abc-123',
                    id: 'xyz-456',
                    teamId: 7,
                    distinctId: '550e8400-e29b-41d4-a716-446655440000',
                }),
                expected: {
                    functionId: 'abc-123',
                    invocationId: 'xyz-456',
                    teamId: '7',
                    actionId: undefined,
                    parentRunId: undefined,
                    distinctId: '550e8400-e29b-41d4-a716-446655440000',
                },
            },
            {
                name: 'omits parentRunId and distinctId when not supplied',
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
                    distinctId: undefined,
                },
            },
            {
                // Webhooks for emails already in flight when the fix deploys must still parse.
                name: 'parses legacy 5-segment codes emitted before distinctId existed',
                encoded: encodeRaw('fn-1:inv-2:3:act-5:batch-4'),
                expected: {
                    functionId: 'fn-1',
                    invocationId: 'inv-2',
                    teamId: '3',
                    actionId: 'act-5',
                    parentRunId: 'batch-4',
                    distinctId: undefined,
                },
            },
            {
                name: 'parses legacy 4-segment codes emitted before parentRunId existed',
                encoded: encodeRaw('fn-1:inv-2:3:act-5'),
                expected: {
                    functionId: 'fn-1',
                    invocationId: 'inv-2',
                    teamId: '3',
                    actionId: 'act-5',
                    parentRunId: undefined,
                    distinctId: undefined,
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
