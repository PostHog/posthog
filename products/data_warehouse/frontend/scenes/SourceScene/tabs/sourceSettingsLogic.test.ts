import type { SourceFieldConfig } from '~/queries/schema/schema-general'

import { isSensitiveCredentialField, removeEmptySensitiveValues } from './sourceSettingsLogic'

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

describe('removeEmptySensitiveValues', () => {
    it('strips blank sensitive scalars from the payload', () => {
        const fields: SourceFieldConfig[] = [
            {
                type: 'password',
                name: 'password',
                label: 'Password',
                required: true,
                placeholder: '',
                secret: true,
            },
            {
                type: 'text',
                name: 'host',
                label: 'Host',
                required: true,
                placeholder: '',
                secret: false,
            },
        ]
        const value: Record<string, any> = { password: '', host: '' }
        removeEmptySensitiveValues(fields, value)
        // Blank password is removed so the backend preserves the existing value.
        // Blank host is left intact so it can fail required validation.
        expect(value).toEqual({ host: '' })
    })

    it('strips blank textarea secrets', () => {
        const fields: SourceFieldConfig[] = [
            {
                type: 'textarea',
                name: 'client_private_key',
                label: 'Client private key',
                required: true,
                placeholder: '',
                secret: true,
            },
        ]
        const value: Record<string, any> = { client_private_key: '' }
        removeEmptySensitiveValues(fields, value)
        expect(value).toEqual({})
    })

    it('keeps non-blank sensitive values', () => {
        const fields: SourceFieldConfig[] = [
            {
                type: 'password',
                name: 'password',
                label: 'Password',
                required: true,
                placeholder: '',
                secret: true,
            },
        ]
        const value: Record<string, any> = { password: 'new-password' }
        removeEmptySensitiveValues(fields, value)
        expect(value).toEqual({ password: 'new-password' })
    })

    it('recurses into select option fields', () => {
        const fields: SourceFieldConfig[] = [
            {
                type: 'select',
                name: 'auth_type',
                label: 'Auth',
                required: true,
                defaultValue: 'keypair',
                options: [
                    {
                        label: 'Keypair',
                        value: 'keypair',
                        fields: [
                            {
                                type: 'text',
                                name: 'user',
                                label: 'User',
                                required: true,
                                placeholder: '',
                                secret: false,
                            },
                            {
                                type: 'textarea',
                                name: 'private_key',
                                label: 'Private key',
                                required: true,
                                placeholder: '',
                                secret: true,
                            },
                        ],
                    },
                ],
            },
        ]
        const value: Record<string, any> = {
            auth_type: { selection: 'keypair', user: 'myuser', private_key: '' },
        }
        removeEmptySensitiveValues(fields, value)
        // Blank private_key dropped from the nested container so the backend's
        // deep-merge preserves the existing value; user kept.
        expect(value).toEqual({
            auth_type: { selection: 'keypair', user: 'myuser' },
        })
    })

    it('recurses into switch-group fields', () => {
        const fields: SourceFieldConfig[] = [
            {
                type: 'switch-group',
                name: 'feature',
                label: 'Feature',
                default: false,
                fields: [
                    {
                        type: 'password',
                        name: 'api_key',
                        label: 'API key',
                        required: true,
                        placeholder: '',
                        secret: true,
                    },
                ],
            },
        ]
        const value: Record<string, any> = {
            feature: { enabled: true, api_key: '' },
        }
        removeEmptySensitiveValues(fields, value)
        expect(value).toEqual({ feature: { enabled: true } })
    })
})
