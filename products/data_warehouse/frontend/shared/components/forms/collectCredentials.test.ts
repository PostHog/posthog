import { collectCredentials } from './CredentialAccountSelector'

describe('collectCredentials', () => {
    const FIELDS = ['client_id', 'private_key']

    it('collects the named fields from a flat payload', () => {
        expect(collectCredentials({ client_id: 'abc', private_key: 'pem', unrelated: 'x' }, FIELDS)).toEqual({
            client_id: 'abc',
            private_key: 'pem',
        })
    })

    it('finds a field nested under a select group', () => {
        // Mirrors how a source with two auth methods stores its fields, the shape the OAuth picker's
        // own lookup exists to handle.
        expect(collectCredentials({ auth_method: { client_id: 'abc', private_key: 'pem' } }, FIELDS)).toEqual({
            client_id: 'abc',
            private_key: 'pem',
        })
    })

    // Every listing attempt costs a token exchange against the provider, and one built from a
    // half-filled form can only fail — so an incomplete payload must not produce a request.
    it.each([
        ['a missing field', { client_id: 'abc' }],
        ['an empty string', { client_id: 'abc', private_key: '' }],
        ['whitespace only', { client_id: 'abc', private_key: '   ' }],
        ['a null', { client_id: 'abc', private_key: null }],
        ['an empty payload', {}],
        ['a non-object payload', undefined],
    ])('returns undefined for %s', (_label, payload) => {
        expect(collectCredentials(payload, FIELDS)).toBeUndefined()
    })

    it('stringifies non-string values', () => {
        expect(collectCredentials({ client_id: 123, private_key: 'pem' }, FIELDS)).toEqual({
            client_id: '123',
            private_key: 'pem',
        })
    })
})
