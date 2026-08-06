import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import type { SourceFieldConfig } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { type ExternalDataSource, type ExternalDataSourceSchema, ExternalDataSchemaStatus } from '~/types'

import { clampSyncFrequency } from 'products/data_warehouse/frontend/utils'

import {
    buildBulkEnablePayloads,
    clonePayloadPreservingFiles,
    isSensitiveCredentialField,
    removeEmptySensitiveValues,
    runBulkSchemaAction,
    schemasEligibleForSync,
    sourceSettingsLogic,
} from './sourceSettingsLogic'

jest.mock('lib/api')

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

describe('clonePayloadPreservingFiles', () => {
    it('preserves File instances in nested payloads', () => {
        const keyFile = new File(['{"project_id":"my-project"}'], 'service-account.json', {
            type: 'application/json',
        })
        const payload = {
            key_file: [keyFile],
            config: { use_custom_region: { enabled: true, region: 'us-east1' } },
        }

        const cloned = clonePayloadPreservingFiles(payload) as Record<string, any>

        expect(cloned).not.toBe(payload)
        expect(cloned.config).not.toBe(payload.config)
        expect(cloned.key_file[0]).toBeInstanceOf(File)
        expect(cloned.key_file[0]).toBe(keyFile)
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

describe('clampSyncFrequency', () => {
    it('floors every schema at 5 minutes, CDC included', () => {
        expect(clampSyncFrequency('1min')).toBe('5min')
        expect(clampSyncFrequency('5min')).toBe('5min')
        expect(clampSyncFrequency('1hour')).toBe('1hour')
    })
})

describe('buildBulkEnablePayloads', () => {
    it('skips already-enabled schemas and requests sync defaults only where no sync method is set', () => {
        const payloads = buildBulkEnablePayloads([
            makeSchema({ id: 'enabled', should_sync: true, sync_type: 'incremental' }),
            makeSchema({ id: 'configured', should_sync: false, sync_type: 'full_refresh' }),
            makeSchema({ id: 'unconfigured', should_sync: false, sync_type: null }),
        ])
        // Sending an unconfigured schema without `apply_sync_defaults` would 400 on the backend
        // ("Sync type must be set up first"); sending it for configured ones is a pointless probe.
        expect(payloads).toEqual([
            { id: 'configured', should_sync: true },
            { id: 'unconfigured', should_sync: true, apply_sync_defaults: true },
        ])
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

describe('sourceSettingsLogic sync refetch', () => {
    let logic: ReturnType<typeof sourceSettingsLogic.build>

    const makeSource = (): ExternalDataSource =>
        ({
            id: 'source-1',
            source_type: 'Postgres',
            status: ExternalDataSchemaStatus.Completed,
            job_inputs: {},
            schemas: [makeSchema({ id: 'schema-1', status: ExternalDataSchemaStatus.Completed })],
        }) as ExternalDataSource

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api.externalDataSources, 'get').mockResolvedValue(makeSource())
        logic = sourceSettingsLogic({ id: 'source-1' })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    // Regression: reloadSchema/resyncSchema optimistically set the row to "Running" but had no
    // finally-refetch, so a rejected or immediately-canceled sync left the row stuck showing Running
    // (or a stale limit badge) until a full page reload. Assert each re-fetches the source afterwards.
    it.each([
        ['reloadSchema', 'reload'],
        ['resyncSchema', 'resync'],
    ] as const)('%s refetches the source after the request settles', async (action, apiMethod) => {
        await expectLogic(logic).toFinishAllListeners()
        jest.spyOn(api.externalDataSchemas, apiMethod).mockResolvedValue(undefined as any)
        const getSpy = jest.spyOn(api.externalDataSources, 'get').mockResolvedValue(makeSource())

        logic.actions[action](makeSchema({ id: 'schema-1' }))
        await expectLogic(logic).toFinishAllListeners()

        expect(getSpy).toHaveBeenCalled()
    })

    it('refetches the source even when the sync request fails', async () => {
        await expectLogic(logic).toFinishAllListeners()
        jest.spyOn(api.externalDataSchemas, 'reload').mockRejectedValue(new Error('Monthly sync limit reached'))
        const getSpy = jest.spyOn(api.externalDataSources, 'get').mockResolvedValue(makeSource())

        logic.actions.reloadSchema(makeSchema({ id: 'schema-1' }))
        await expectLogic(logic).toFinishAllListeners()

        expect(getSpy).toHaveBeenCalled()
    })
})
