import { HogFunctionType } from '../types'
import { mergeSecretHeaders, resolveSecretHeaders } from './secret-headers'

describe('secret headers', () => {
    const hogFunctionWith = (
        inputs: Record<string, any>,
        encryptedInputs?: Record<string, any>
    ): Pick<HogFunctionType, 'inputs' | 'encrypted_inputs'> => ({
        inputs,
        encrypted_inputs: encryptedInputs,
    })

    describe('resolveSecretHeaders', () => {
        // Secrets move to encrypted_inputs on save, but a row saved before its template
        // marked the input secret still has the plaintext copy. The encrypted value must
        // win, or rotating a credential would silently keep sending the old one.
        it.each([
            ['encrypted only', {}, { secret_headers: { value: { 'x-api-token': 'tok_123' } } }, 'tok_123'],
            ['plaintext only', { secret_headers: { value: { 'x-api-token': 'tok_123' } } }, undefined, 'tok_123'],
            [
                'both',
                { secret_headers: { value: { 'x-api-token': 'stale' } } },
                { secret_headers: { value: { 'x-api-token': 'current' } } },
                'current',
            ],
        ])('resolves with %s', (_name, inputs, encryptedInputs, expected) => {
            const resolved = resolveSecretHeaders('secret_headers', hogFunctionWith(inputs, encryptedInputs))

            expect(resolved).toEqual({ ok: true, headers: { 'x-api-token': expected } })
        })

        it('stringifies scalar values', () => {
            const resolved = resolveSecretHeaders(
                'secret_headers',
                hogFunctionWith({}, { secret_headers: { value: { 'x-version': 42, 'x-beta': true } } })
            )

            expect(resolved).toEqual({ ok: true, headers: { 'x-version': '42', 'x-beta': 'true' } })
        })

        // Every failure below has the same consequence if it were tolerated: the request
        // reaches the receiver with its credential header missing.
        it.each([
            ['a missing input', {}, /was not found on this destination/],
            ['a non-dictionary value', { secret_headers: { value: 'tok_123' } }, /is not a dictionary/],
            ['an array value', { secret_headers: { value: ['tok_123'] } }, /is not a dictionary/],
            ['an empty dictionary', { secret_headers: { value: {} } }, /is empty/],
            ['a nested value', { secret_headers: { value: { auth: { nested: 'x' } } } }, /is not a string/],
            ['an empty header value', { secret_headers: { value: { 'x-api-token': '' } } }, /is empty/],
        ])('fails closed on %s', (_name, inputs, expectedError) => {
            const resolved = resolveSecretHeaders('secret_headers', hogFunctionWith(inputs))

            expect(resolved.ok).toBe(false)
            expect((resolved as { ok: false; error: string }).error).toMatch(expectedError)
        })
    })

    describe('mergeSecretHeaders', () => {
        it('merges alongside plaintext headers', () => {
            expect(mergeSecretHeaders({ 'Content-Type': 'application/json' }, { 'x-api-token': 'tok_123' })).toEqual({
                'Content-Type': 'application/json',
                'x-api-token': 'tok_123',
            })
        })

        // Header names are case-insensitive, so keeping both would put two Authorization
        // headers on the wire and let the plaintext one win at some receivers.
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
