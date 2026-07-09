import { defaultConfig } from '~/common/config/config'

import { EmailTrackingCodeSigner, hasEmailSigningKey, trackingCodeMintCounter } from './tracking-code'

const TRACKING_URL = 'http://localhost:8010'

// Hand-encode a raw payload the same way the signer does, so we can test
// pre-fix legacy/forged shapes without pulling in the generator.
const encodeRaw = (payload: string): string =>
    Buffer.from(payload, 'utf8').toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')

describe('email tracking code', () => {
    // Runs with ENCRYPTION_SALT_KEYS set in the test env, so codes are signed by default.
    const signer = new EmailTrackingCodeSigner(defaultConfig.ENCRYPTION_SALT_KEYS, TRACKING_URL)

    describe('parse', () => {
        it.each([
            {
                // Generated codes are signed in the test env (ENCRYPTION_SALT_KEYS is set).
                name: 'roundtrips all invocation fields including distinctId (signed)',
                encoded: signer.generate({
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
                encoded: signer.generate(
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
                encoded: signer.generate({ functionId: 'fn-1', id: 'inv-2', teamId: 3 }, true),
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
                encoded: signer.generate({
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
                    distinctId: undefined,
                    format: 'signed',
                },
            },
            {
                // The short code (SES tag carrier) is never signed and omits distinctId/isTest.
                name: 'parses the unsigned short code used for the SES tag',
                encoded: signer.generateShort({
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
            const tampered = `${encodeRaw('attacker:invX:1:::')}.${sig}`
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
            // Rotation: new key first, old key kept for the verification grace period.
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

        it('fails closed instead of minting an unsigned code when no signing key is configured', () => {
            const unsignedSigner = new EmailTrackingCodeSigner('', TRACKING_URL)
            expect(() => unsignedSigner.generate({ functionId: 'fn', id: 'inv', teamId: 1 })).toThrow(
                /no signing key configured/
            )
        })
    })

    describe('mint metric', () => {
        const mintCount = async (format: string): Promise<number> => {
            const metric = await trackingCodeMintCounter.get()
            return metric.values.find((v) => v.labels.format === format)?.value ?? 0
        }

        it('counts a signed mint when a key is configured', async () => {
            const before = await mintCount('signed')
            new EmailTrackingCodeSigner(defaultConfig.ENCRYPTION_SALT_KEYS, TRACKING_URL).generate({
                functionId: 'fn',
                id: 'inv',
                teamId: 1,
            })
            expect(await mintCount('signed')).toBe(before + 1)
        })

        // Fail-closed still records the attempt before throwing, so a bypassed boot guard stays attributable.
        it('records an unsigned mint before failing closed when no key is configured', async () => {
            const before = await mintCount('unsigned')
            expect(() =>
                new EmailTrackingCodeSigner('', TRACKING_URL).generate({ functionId: 'fn', id: 'inv', teamId: 1 })
            ).toThrow()
            expect(await mintCount('unsigned')).toBe(before + 1)
        })
    })

    describe('hasEmailSigningKey', () => {
        // Guards the boot-time check: a whitespace/comma-only value must read as "no key" so a keyless
        // email deployment refuses to start, while a real (possibly space-padded) key reads as present.
        it.each([
            { name: 'a configured key', keys: 'a-signing-key-000000000000000000', expected: true },
            { name: 'a space-padded key in a rotation list', keys: 'first-key-0000, second-key-0000', expected: true },
            { name: 'an empty string', keys: '', expected: false },
            { name: 'whitespace and commas only', keys: '  , ', expected: false },
        ])('is $expected for $name', ({ keys, expected }) => {
            expect(hasEmailSigningKey(keys)).toBe(expected)
        })
    })
})
