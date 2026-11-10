import { EncryptedFields } from './encryption-utils'
import {
    IntegrationInputRef,
    IntegrationInputRefsRollout,
    isSignedIntegrationRef,
    markServerResolvedIntegration,
    replaceIntegrationInputsWithRefs,
    signIntegrationRef,
} from './integration-input-refs'

describe('signed integration references', () => {
    const OLD_KEY = '00beef0000beef0000beef0000beef00'
    const NEW_KEY = '11beef1111beef1111beef1111beef11'
    const signer = new EncryptedFields(OLD_KEY)

    const ref = (id: number, signature: unknown): IntegrationInputRef => ({
        $integration_ref: id,
        $integration_ref_sig: signature,
    })

    it('signs each resolved integration with the input key and verifies it for the same team, key and id', () => {
        const inputs = replaceIntegrationInputsWithRefs(
            {
                twilio: markServerResolvedIntegration({ $integration_id: 41, auth_token: 'fake-token' }),
                channels: [markServerResolvedIntegration({ $integration_id: 42 })],
            },
            (key, id) => signIntegrationRef(signer, 7, key, id)
        )

        expect(JSON.stringify(inputs)).not.toContain('fake-token')
        expect(isSignedIntegrationRef(signer, 7, 'twilio', inputs.twilio)).toBe(true)
        expect(isSignedIntegrationRef(signer, 7, 'channels', inputs.channels[0])).toBe(true)
    })

    it('does not sign an object that event data shaped like a resolved integration', () => {
        const inputs = { payload: { $integration_id: 41 }, channels: [{ $integration_id: 42 }] }

        expect(replaceIntegrationInputsWithRefs(inputs, (key, id) => signIntegrationRef(signer, 7, key, id))).toBe(
            inputs
        )
    })

    it.each<[string, () => { verifier: EncryptedFields; teamId: number; key: string; ref: IntegrationInputRef }]>([
        ['no signature', () => ({ verifier: signer, teamId: 7, key: 'payload', ref: { $integration_ref: 41 } })],
        ['a signature that is not a string', () => ({ verifier: signer, teamId: 7, key: 'payload', ref: ref(41, 1) })],
        ['a made-up signature', () => ({ verifier: signer, teamId: 7, key: 'payload', ref: ref(41, 'a'.repeat(64)) })],
        [
            'a signature from a key that is no longer configured',
            () => ({
                verifier: new EncryptedFields(NEW_KEY),
                teamId: 7,
                key: 'payload',
                ref: ref(41, signIntegrationRef(signer, 7, 'payload', 41)),
            }),
        ],
    ])('rejects a reference with %s', (_name, build) => {
        const { verifier, teamId, key, ref } = build()

        expect(isSignedIntegrationRef(verifier, teamId, key, ref)).toBe(false)
    })

    it('accepts a reference signed with an older key after a key rotation', () => {
        const rotated = new EncryptedFields(`${NEW_KEY},${OLD_KEY}`)

        expect(
            isSignedIntegrationRef(rotated, 7, 'payload', ref(41, signIntegrationRef(signer, 7, 'payload', 41)))
        ).toBe(true)
        expect(signIntegrationRef(rotated, 7, 'payload', 41)).not.toBe(signIntegrationRef(signer, 7, 'payload', 41))
    })
})

describe('IntegrationInputRefsRollout', () => {
    const flushPromises = () => new Promise((resolve) => setImmediate(resolve))

    afterEach(() => {
        jest.restoreAllMocks()
    })

    const cases: [string, () => Promise<boolean>, boolean][] = [
        ['an enabled flag', () => Promise.resolve(true), true],
        ['a disabled flag', () => Promise.resolve(false), false],
        ['a failed evaluation', () => Promise.reject(new Error('flags unavailable')), false],
    ]

    it.each(cases)(
        'reads the flag without waiting and evaluates it once per minute, given %s',
        async (_name, result, expected) => {
            let now = 1_000_000
            jest.spyOn(Date, 'now').mockImplementation(() => now)
            const evaluate = jest.fn(result)
            const rollout = new IntegrationInputRefsRollout(evaluate)

            expect(rollout.isEnabled()).toBe(false)
            expect(rollout.isEnabled()).toBe(false)
            await flushPromises()
            expect(rollout.isEnabled()).toBe(expected)
            expect(evaluate).toHaveBeenCalledTimes(1)

            now += 60_000
            rollout.isEnabled()
            await flushPromises()
            expect(evaluate).toHaveBeenCalledTimes(2)
        }
    )
})
