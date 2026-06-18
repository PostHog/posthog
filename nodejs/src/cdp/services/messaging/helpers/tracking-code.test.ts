import { defaultConfig } from '~/config/config'

import { generateEmailTrackingCode, generateShortEmailTrackingCode, parseEmailTrackingCode } from './tracking-code'

// Hand-encode a raw payload the same way the generators do, so we can test pre-fix legacy
// (unsigned) shapes without pulling in the generator.
const encodeRaw = (payload: string): string =>
    Buffer.from(payload, 'utf8').toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')

describe('email tracking code', () => {
    describe('parseEmailTrackingCode', () => {
        it.each([
            {
                // Generated codes are signed in the test env (ENCRYPTION_SALT_KEYS is set).
                name: 'roundtrips all invocation fields including distinctId (signed)',
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
                    isTest: false,
                    distinctId: 'user@example.com',
                    format: 'signed',
                },
            },
            {
                name: 'roundtrips the isTest flag for test sends',
                encoded: generateEmailTrackingCode(
                    {
                        functionId: 'fn-1',
                        id: 'inv-2',
                        teamId: 3,
                        parentRunId: 'batch-4',
                        state: { actionId: 'act-5' },
                        distinctId: 'user@example.com',
                    },
                    true
                ),
                expected: {
                    functionId: 'fn-1',
                    invocationId: 'inv-2',
                    teamId: '3',
                    actionId: 'act-5',
                    parentRunId: 'batch-4',
                    isTest: true,
                    distinctId: 'user@example.com',
                    format: 'signed',
                },
            },
            {
                // isTest sits after actionId/parentRunId, so it must survive both being empty.
                name: 'roundtrips isTest when neither actionId nor parentRunId is supplied',
                encoded: generateEmailTrackingCode({ functionId: 'fn-1', id: 'inv-2', teamId: 3 }, true),
                expected: {
                    functionId: 'fn-1',
                    invocationId: 'inv-2',
                    teamId: '3',
                    actionId: undefined,
                    parentRunId: undefined,
                    isTest: true,
                    distinctId: undefined,
                    format: 'signed',
                },
            },
            {
                name: 'roundtrips with UUID distinctId (signed)',
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
                    isTest: false,
                    distinctId: '550e8400-e29b-41d4-a716-446655440000',
                    format: 'signed',
                },
            },
            {
                name: 'omits parentRunId and distinctId when not supplied (signed)',
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
                    isTest: false,
                    distinctId: undefined,
                    format: 'signed',
                },
            },
            {
                // The short code (SES tag carrier) is never signed and omits distinctId/isTest.
                name: 'parses the unsigned short code used for the SES tag',
                encoded: generateShortEmailTrackingCode({
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
                    isTest: false,
                    distinctId: undefined,
                    format: 'unsigned',
                },
            },
            {
                // Webhooks for emails already in flight when the fix deploys must still parse.
                name: 'parses legacy 4-segment unsigned codes emitted before parentRunId existed',
                encoded: encodeRaw('fn-1:inv-2:3:act-5'),
                expected: {
                    functionId: 'fn-1',
                    invocationId: 'inv-2',
                    teamId: '3',
                    actionId: 'act-5',
                    parentRunId: undefined,
                    isTest: false,
                    distinctId: undefined,
                    format: 'unsigned',
                },
            },
            {
                name: 'parses legacy 5-segment unsigned codes emitted before isTest/distinctId existed',
                encoded: encodeRaw('fn-1:inv-2:3:act-5:batch-4'),
                expected: {
                    functionId: 'fn-1',
                    invocationId: 'inv-2',
                    teamId: '3',
                    actionId: 'act-5',
                    parentRunId: 'batch-4',
                    isTest: false,
                    distinctId: undefined,
                    format: 'unsigned',
                },
            },
            {
                // Deployed master codes carry isTest at position 6 and no distinctId — must keep parsing.
                name: 'parses legacy 6-segment codes with isTest at position 6 and no distinctId',
                encoded: encodeRaw('fn-1:inv-2:3:act-5:batch-4:1'),
                expected: {
                    functionId: 'fn-1',
                    invocationId: 'inv-2',
                    teamId: '3',
                    actionId: 'act-5',
                    parentRunId: 'batch-4',
                    isTest: true,
                    distinctId: undefined,
                    format: 'unsigned',
                },
            },
            {
                // Security: a forged UNSIGNED code carrying a distinct_id must NOT be trusted —
                // distinct_id is only honored from signed codes, so this one parses with no distinctId.
                name: 'ignores distinct_id on an unsigned (forged) code',
                encoded: encodeRaw('fn-1:inv-2:3:act-5:batch-4::attacker-distinct-id'),
                expected: {
                    functionId: 'fn-1',
                    invocationId: 'inv-2',
                    teamId: '3',
                    actionId: 'act-5',
                    parentRunId: 'batch-4',
                    isTest: false,
                    distinctId: undefined,
                    format: 'unsigned',
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

    describe('signed tracking codes', () => {
        it('emits codes with a `.` separator when signing keys are configured', () => {
            const code = generateEmailTrackingCode({ functionId: 'fn', id: 'inv', teamId: 1 })
            expect(code).toContain('.')
        })

        it('does not sign the short code used for the SES tag', () => {
            const short = generateShortEmailTrackingCode({ functionId: 'fn', id: 'inv', teamId: 1 })
            expect(short).not.toContain('.')
            expect(parseEmailTrackingCode(short)?.format).toBe('unsigned')
        })

        it('rejects a signed code with a tampered payload', () => {
            const code = generateEmailTrackingCode({ functionId: 'fn', id: 'inv', teamId: 1 })
            const sig = code.split('.')[1]
            // Mint a different payload but reuse the original signature.
            const tampered = `${encodeRaw('attacker:invX:1:::')}.${sig}`
            expect(parseEmailTrackingCode(tampered)).toBeNull()
        })

        it('rejects a signed code with a tampered signature', () => {
            const code = generateEmailTrackingCode({ functionId: 'fn', id: 'inv', teamId: 1 })
            const payload = code.split('.')[0]
            // 16 raw bytes -> 22 base64url chars
            const badSig = 'A'.repeat(22)
            expect(parseEmailTrackingCode(`${payload}.${badSig}`)).toBeNull()
        })

        it('rejects a signed code with a malformed (wrong-length) signature', () => {
            const code = generateEmailTrackingCode({ functionId: 'fn', id: 'inv', teamId: 1 })
            const payload = code.split('.')[0]
            expect(parseEmailTrackingCode(`${payload}.short`)).toBeNull()
        })

        it('rejects a code with extra `.` segments appended', () => {
            // Both payload and signature are base64url (no dots), so a legitimate signed code
            // is structurally exactly `<payload>.<signature>`. Anything else is malformed.
            const code = generateEmailTrackingCode({ functionId: 'fn', id: 'inv', teamId: 1 })
            expect(parseEmailTrackingCode(`${code}.junk`)).toBeNull()
        })

        it('rejects when no signing key matches', () => {
            const code = generateEmailTrackingCode({ functionId: 'fn', id: 'inv', teamId: 1 })
            const original = defaultConfig.ENCRYPTION_SALT_KEYS
            defaultConfig.ENCRYPTION_SALT_KEYS = 'a-completely-different-key-32-chr'
            try {
                expect(parseEmailTrackingCode(code)).toBeNull()
            } finally {
                defaultConfig.ENCRYPTION_SALT_KEYS = original
            }
        })

        it('verifies against any key in the rotation list', () => {
            const original = defaultConfig.ENCRYPTION_SALT_KEYS
            defaultConfig.ENCRYPTION_SALT_KEYS = 'old-key-aaaaaaaaaaaaaaaaaaaaaaaa'
            const code = generateEmailTrackingCode({ functionId: 'fn', id: 'inv', teamId: 1 })
            // Rotation: new key first, old key kept for the verification grace period.
            defaultConfig.ENCRYPTION_SALT_KEYS = 'new-key-bbbbbbbbbbbbbbbbbbbbbbbb,old-key-aaaaaaaaaaaaaaaaaaaaaaaa'
            try {
                expect(parseEmailTrackingCode(code)?.format).toBe('signed')
            } finally {
                defaultConfig.ENCRYPTION_SALT_KEYS = original
            }
        })

        it('trims whitespace around keys in the rotation list', () => {
            const original = defaultConfig.ENCRYPTION_SALT_KEYS
            defaultConfig.ENCRYPTION_SALT_KEYS = 'signing-key-cccccccccccccccccccc'
            const code = generateEmailTrackingCode({ functionId: 'fn', id: 'inv', teamId: 1 })
            // Same keys, but configured with a space after the comma — must still verify.
            defaultConfig.ENCRYPTION_SALT_KEYS = 'other-key-dddddddddddddddddddddd, signing-key-cccccccccccccccccccc'
            try {
                expect(parseEmailTrackingCode(code)?.format).toBe('signed')
            } finally {
                defaultConfig.ENCRYPTION_SALT_KEYS = original
            }
        })

        it('emits unsigned codes when no signing key is configured', () => {
            const original = defaultConfig.ENCRYPTION_SALT_KEYS
            defaultConfig.ENCRYPTION_SALT_KEYS = ''
            try {
                const code = generateEmailTrackingCode({ functionId: 'fn', id: 'inv', teamId: 1 })
                expect(code).not.toContain('.')
                expect(parseEmailTrackingCode(code)?.format).toBe('unsigned')
            } finally {
                defaultConfig.ENCRYPTION_SALT_KEYS = original
            }
        })
    })
})
