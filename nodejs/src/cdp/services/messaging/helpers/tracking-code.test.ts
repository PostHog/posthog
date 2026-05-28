import { defaultConfig } from '~/config/config'

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
                    format: 'signed',
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
                    format: 'signed',
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
                    format: 'unsigned',
                },
            },
            {
                name: 'parses legacy 5-segment unsigned codes emitted before signing existed',
                encoded: encodeRaw('fn-1:inv-2:3:act-5:batch-4'),
                expected: {
                    functionId: 'fn-1',
                    invocationId: 'inv-2',
                    teamId: '3',
                    actionId: 'act-5',
                    parentRunId: 'batch-4',
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

        it('rejects a signed code with a tampered payload', () => {
            const code = generateEmailTrackingCode({ functionId: 'fn', id: 'inv', teamId: 1 })
            const sig = code.split('.')[1]
            // Mint a different payload but reuse the original signature.
            const tampered = `${encodeRaw('attacker:invX:1::')}.${sig}`
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
            // Rotation: new key first, old key kept for verification grace period.
            defaultConfig.ENCRYPTION_SALT_KEYS = 'new-key-bbbbbbbbbbbbbbbbbbbbbbbb,old-key-aaaaaaaaaaaaaaaaaaaaaaaa'
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
