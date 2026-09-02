import { HogFunctionType } from '../types'
import { mergeInputsForVm, mergeSecretHeaders, resolveSecretEntries } from './secret-entries'

describe('secret entries', () => {
    const perEntryHeaders = {
        inputs: {
            headers: { value: { 'Content-Type': 'application/json' }, secret_keys: ['x-api-token'] },
        },
        encrypted_inputs: {
            headers: { value: { 'x-api-token': 'tok_HqZ2NmVrTt' } },
        },
    } as unknown as Pick<HogFunctionType, 'inputs' | 'encrypted_inputs'>

    describe('mergeInputsForVm', () => {
        // The old shallow spread let encrypted_inputs.headers replace the whole input, so the VM
        // would have seen only the credential and lost every plaintext header.
        it('keeps the public half of a per-entry input', () => {
            const merged = mergeInputsForVm(perEntryHeaders.inputs, perEntryHeaders.encrypted_inputs)

            expect(merged?.headers?.value).toEqual({ 'Content-Type': 'application/json' })
        })

        it('replaces a whole-input secret with its stored value', () => {
            const merged = mergeInputsForVm(
                { signing_secret: { value: null } } as any,
                { signing_secret: { value: 'whsec_x' } } as any
            )

            expect(merged?.signing_secret?.value).toEqual('whsec_x')
        })
    })

    describe('resolveSecretEntries', () => {
        it('resolves the declared entries', () => {
            expect(resolveSecretEntries('headers', perEntryHeaders)).toEqual({
                ok: true,
                entries: { 'x-api-token': 'tok_HqZ2NmVrTt' },
            })
        })

        // The ordinary case for a destination that sends no credentials. Failing here would break
        // every existing webhook, since the template names the input unconditionally.
        it('resolves to nothing when no entry is declared secret', () => {
            const resolved = resolveSecretEntries('headers', {
                inputs: { headers: { value: { 'Content-Type': 'application/json' } } },
            } as any)

            expect(resolved).toEqual({ ok: true, entries: {} })
        })

        it('stringifies scalar values', () => {
            const resolved = resolveSecretEntries('headers', {
                inputs: { headers: { value: {}, secret_keys: ['x-version', 'x-beta'] } },
                encrypted_inputs: { headers: { value: { 'x-version': 42, 'x-beta': true } } },
            } as any)

            expect(resolved).toEqual({ ok: true, entries: { 'x-version': '42', 'x-beta': 'true' } })
        })

        // Each of these would otherwise send the request with its credential header missing, which
        // the receiver reads as an unauthenticated caller.
        it.each([
            ['nothing stored at all', { headers: { value: {}, secret_keys: ['x-api-token'] } }, undefined],
            [
                'one declared entry unstored',
                { headers: { value: {}, secret_keys: ['x-api-token', 'x-other'] } },
                { headers: { value: { 'x-api-token': 'tok' } } },
            ],
            [
                'an empty stored value',
                { headers: { value: {}, secret_keys: ['x-api-token'] } },
                { headers: { value: { 'x-api-token': '' } } },
            ],
            [
                'a nested stored value',
                { headers: { value: {}, secret_keys: ['x-api-token'] } },
                { headers: { value: { 'x-api-token': { nested: 'x' } } } },
            ],
        ])('fails closed on %s', (_name, inputs, encryptedInputs) => {
            const resolved = resolveSecretEntries('headers', { inputs, encrypted_inputs: encryptedInputs } as any)

            expect(resolved.ok).toBe(false)
            expect((resolved as { ok: false; error: string }).error).toMatch(/Secret headers failed to resolve/)
        })
    })

    describe('mergeSecretHeaders', () => {
        it('merges alongside plaintext headers', () => {
            expect(mergeSecretHeaders({ 'Content-Type': 'application/json' }, { 'x-api-token': 'tok_123' })).toEqual({
                'Content-Type': 'application/json',
                'x-api-token': 'tok_123',
            })
        })

        // Header names are case-insensitive, so keeping both would put two Authorization headers
        // on the wire and let the plaintext one win at some receivers.
        it('replaces a plaintext header of the same name, whatever its casing', () => {
            expect(
                mergeSecretHeaders(
                    { authorization: 'Bearer placeholder', 'Content-Type': 'application/json' },
                    { Authorization: 'Bearer real' }
                )
            ).toEqual({ 'Content-Type': 'application/json', Authorization: 'Bearer real' })
        })
    })
})
