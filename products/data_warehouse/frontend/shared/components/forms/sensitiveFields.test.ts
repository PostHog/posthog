import type { SourceFieldConfig } from '~/queries/schema/schema-general'

import { isSensitiveCredentialField } from './sensitiveFields'

describe('isSensitiveCredentialField', () => {
    it('treats password-typed fields as sensitive', () => {
        const field: SourceFieldConfig = {
            type: 'password',
            name: 'password',
            label: 'Password',
            required: true,
            placeholder: '',
            secret: true,
        }
        expect(isSensitiveCredentialField(field)).toBe(true)
    })

    it('treats any field with secret=true as sensitive regardless of type', () => {
        // Regression: TEXTAREA-rendered secrets like Temporal client_private_key
        // and Snowflake keypair private_key need to be detected by the secret flag,
        // not by their input type or hardcoded name.
        const field: SourceFieldConfig = {
            type: 'textarea',
            name: 'client_private_key',
            label: 'Client private key',
            required: true,
            placeholder: '',
            secret: true,
        }
        expect(isSensitiveCredentialField(field)).toBe(true)
    })

    it('does not treat plain text fields as sensitive', () => {
        const field: SourceFieldConfig = {
            type: 'text',
            name: 'host',
            label: 'Host',
            required: true,
            placeholder: '',
            secret: false,
        }
        expect(isSensitiveCredentialField(field)).toBe(false)
    })
})
