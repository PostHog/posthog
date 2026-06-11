import type { SourceFieldConfig } from '~/queries/schema/schema-general'
import type { ExternalDataSourceSchema } from '~/types'

import {
    clampFrequencyForSchema,
    isSensitiveCredentialField,
    removeEmptySensitiveValues,
    runBulkSchemaAction,
    schemasEligibleForSync,
} from './sourceSettingsLogic'

function makeSchema(overrides: Partial<ExternalDataSourceSchema>): ExternalDataSourceSchema {
    return {
        id: 'schema-id',
        name: 'public.table',
        should_sync: false,
        sync_type: null,
        ...overrides,
    } as ExternalDataSourceSchema
}

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

describe('schemasEligibleForSync', () => {
    it('keeps only schemas that are enabled with a sync method', () => {
        const schemas = [
            makeSchema({ id: 'a', sync_type: 'incremental', should_sync: true }),
            makeSchema({ id: 'b', sync_type: 'incremental', should_sync: false }), // disabled
            makeSchema({ id: 'c', sync_type: null, should_sync: true }), // no method
            makeSchema({ id: 'd', sync_type: 'cdc', should_sync: true }),
        ]
        expect(schemasEligibleForSync(schemas).map((s) => s.id)).toEqual(['a', 'd'])
    })

    it('returns an empty list when nothing is eligible', () => {
        expect(schemasEligibleForSync([makeSchema({ sync_type: null, should_sync: true })])).toEqual([])
    })
})

describe('clampFrequencyForSchema', () => {
    it('floors non-CDC schemas at 5 minutes', () => {
        const incremental = makeSchema({ sync_type: 'incremental' })
        expect(clampFrequencyForSchema('1min', incremental)).toBe('5min')
        expect(clampFrequencyForSchema('5min', incremental)).toBe('5min')
        expect(clampFrequencyForSchema('1hour', incremental)).toBe('1hour')
    })

    it('lets CDC schemas go down to 1 minute', () => {
        const cdc = makeSchema({ sync_type: 'cdc' })
        expect(clampFrequencyForSchema('1min', cdc)).toBe('1min')
        expect(clampFrequencyForSchema('6hour', cdc)).toBe('6hour')
    })
})

describe('runBulkSchemaAction', () => {
    it('invokes the action for every schema and reports zero failures on success', async () => {
        const schemas = [makeSchema({ id: 'a' }), makeSchema({ id: 'b' })]
        const action = jest.fn().mockResolvedValue(undefined)
        const failed = await runBulkSchemaAction(schemas, action)
        expect(action).toHaveBeenCalledTimes(2)
        expect(action).toHaveBeenCalledWith('a')
        expect(action).toHaveBeenCalledWith('b')
        expect(failed).toBe(0)
    })

    it('counts rejected actions without throwing', async () => {
        const schemas = [makeSchema({ id: 'a' }), makeSchema({ id: 'b' }), makeSchema({ id: 'c' })]
        const action = jest.fn((id: string) => (id === 'b' ? Promise.reject(new Error('boom')) : Promise.resolve()))
        const failed = await runBulkSchemaAction(schemas, action)
        expect(failed).toBe(1)
        expect(action).toHaveBeenCalledTimes(3)
    })
})
