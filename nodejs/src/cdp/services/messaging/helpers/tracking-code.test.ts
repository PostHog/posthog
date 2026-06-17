import { defaultConfig } from '~/config/config'

import { EmailTrackingCodeSigner } from './tracking-code'

const TRACKING_URL = 'http://localhost:8010'

// Hand-encode a raw payload the same way the signer does, so we can test
// pre-fix legacy shapes (4-segment) without pulling in the generator.
const encodeRaw = (payload: string): string =>
    Buffer.from(payload, 'utf8').toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')

describe('email tracking code', () => {
    // Runs with ENCRYPTION_SALT_KEYS set in the test env, so codes are signed by default.
    const signer = new EmailTrackingCodeSigner(defaultConfig.ENCRYPTION_SALT_KEYS, TRACKING_URL)

    describe('parse', () => {
        it.each([
            {
                name: 'roundtrips all invocation fields including parentRunId',
                encoded: signer.generate({
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
                    isTest: false,
                    format: 'signed',
                },
            },
            {
                name: 'roundtrips the isTest flag for test sends',
                encoded: signer.generate(
                    {
                        functionId: 'fn-1',
                        id: 'inv-2',
                        teamId: 3,
                        parentRunId: 'batch-4',
                        state: { actionId: 'act-5' },
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
                    format: 'signed',
                },
            },
            {
                // isTest sits after actionId/parentRunId, so it must survive both being empty.
                name: 'roundtrips isTest when neither actionId nor parentRunId is supplied',
                encoded: signer.generate({ functionId: 'fn-1', id: 'inv-2', teamId: 3 }, true),
                expected: {
                    functionId: 'fn-1',
                    invocationId: 'inv-2',
                    teamId: '3',
                    actionId: undefined,
                    parentRunId: undefined,
                    isTest: true,
                    format: 'signed',
                },
            },
            {
                name: 'omits parentRunId when not supplied',
                encoded: signer.generate({
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
                    isTest: false,
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
                    isTest: false,
                    format: 'unsigned',
                },
            },
            {
                name: 'returns null when the encoded string is empty',
                encoded: '',
                expected: null,
            },
        ])('$name', ({ encoded, expected }) => {
            expect(signer.parse(encoded)).toEqual(expected)
        })
    })

    describe('signed tracking codes', () => {
        it('emits codes with a `.` separator when signing keys are configured', () => {
            const code = signer.generate({ functionId: 'fn', id: 'inv', teamId: 1 })
            expect(code).toContain('.')
        })

        it('does not sign the short code used for the SES tag', () => {
            const short = signer.generateShort({ functionId: 'fn', id: 'inv', teamId: 1 })
            expect(short).not.toContain('.')
            expect(signer.parse(short)?.format).toBe('unsigned')
        })

        it('rejects a signed code with a tampered payload', () => {
            const code = signer.generate({ functionId: 'fn', id: 'inv', teamId: 1 })
            const sig = code.split('.')[1]
            // Mint a different payload but reuse the original signature.
            const tampered = `${encodeRaw('attacker:invX:1::')}.${sig}`
            expect(signer.parse(tampered)).toBeNull()
        })

        it('rejects a signed code with a tampered signature', () => {
            const code = signer.generate({ functionId: 'fn', id: 'inv', teamId: 1 })
            const payload = code.split('.')[0]
            // 16 raw bytes -> 22 base64url chars
            const badSig = 'A'.repeat(22)
            expect(signer.parse(`${payload}.${badSig}`)).toBeNull()
        })

        it('rejects a signed code with a malformed (wrong-length) signature', () => {
            const code = signer.generate({ functionId: 'fn', id: 'inv', teamId: 1 })
            const payload = code.split('.')[0]
            expect(signer.parse(`${payload}.short`)).toBeNull()
        })

        it('rejects a code with extra `.` segments appended', () => {
            // Both payload and signature are base64url (no dots), so a legitimate signed code
            // is structurally exactly `<payload>.<signature>`. Anything else is malformed.
            const code = signer.generate({ functionId: 'fn', id: 'inv', teamId: 1 })
            expect(signer.parse(`${code}.junk`)).toBeNull()
        })

        it('rejects when no signing key matches', () => {
            const code = signer.generate({ functionId: 'fn', id: 'inv', teamId: 1 })
            const otherSigner = new EmailTrackingCodeSigner('a-completely-different-key-32-chr', TRACKING_URL)
            expect(otherSigner.parse(code)).toBeNull()
        })

        it('verifies against any key in the rotation list', () => {
            const oldSigner = new EmailTrackingCodeSigner('old-key-aaaaaaaaaaaaaaaaaaaaaaaa', TRACKING_URL)
            const code = oldSigner.generate({ functionId: 'fn', id: 'inv', teamId: 1 })
            // Rotation: new key first, old key kept for verification grace period.
            const rotatedSigner = new EmailTrackingCodeSigner(
                'new-key-bbbbbbbbbbbbbbbbbbbbbbbb,old-key-aaaaaaaaaaaaaaaaaaaaaaaa',
                TRACKING_URL
            )
            expect(rotatedSigner.parse(code)?.format).toBe('signed')
        })

        it('trims whitespace around keys in the rotation list', () => {
            const signingSigner = new EmailTrackingCodeSigner('signing-key-cccccccccccccccccccc', TRACKING_URL)
            const code = signingSigner.generate({ functionId: 'fn', id: 'inv', teamId: 1 })
            // Same keys, but configured with a space after the comma — must still verify.
            const spacedSigner = new EmailTrackingCodeSigner(
                'other-key-dddddddddddddddddddddd, signing-key-cccccccccccccccccccc',
                TRACKING_URL
            )
            expect(spacedSigner.parse(code)?.format).toBe('signed')
        })

        it('emits unsigned codes when no signing key is configured', () => {
            const unsignedSigner = new EmailTrackingCodeSigner('', TRACKING_URL)
            const code = unsignedSigner.generate({ functionId: 'fn', id: 'inv', teamId: 1 })
            expect(code).not.toContain('.')
            expect(unsignedSigner.parse(code)?.format).toBe('unsigned')
        })
    })
})
