import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SourceConfigResponseApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { availableSourcesLogic } from '../NewSourceScene/availableSourcesLogic'
import { sourceConnectSceneLogic } from './sourceConnectSceneLogic'

const AVAILABLE_SOURCES: Record<string, SourceConfigResponseApi> = {
    Postgres: {
        name: 'Postgres',
        iconPath: '',
        caption: '',
        fields: [{ type: 'text', name: 'host', label: 'Host', required: true, placeholder: '' }],
    } as unknown as SourceConfigResponseApi,
    Hubspot: {
        name: 'Hubspot',
        iconPath: '',
        caption: '',
        fields: [
            {
                type: 'oauth',
                name: 'hubspot_integration_id',
                label: 'Hubspot account',
                required: true,
                kind: 'hubspot',
            },
        ],
    } as unknown as SourceConfigResponseApi,
    Stripe: {
        name: 'Stripe',
        iconPath: '',
        caption: '',
        fields: [
            {
                type: 'select',
                name: 'auth_method',
                label: 'Auth method',
                required: true,
                defaultValue: 'api_key',
                options: [
                    {
                        label: 'API key',
                        value: 'api_key',
                        fields: [
                            {
                                type: 'password',
                                name: 'stripe_secret_key',
                                label: 'Secret key',
                                required: true,
                                placeholder: '',
                            },
                        ],
                    },
                    {
                        label: 'OAuth',
                        value: 'oauth',
                        fields: [
                            {
                                type: 'oauth',
                                name: 'stripe_integration_id',
                                label: 'Stripe account',
                                required: true,
                                kind: 'stripe',
                            },
                        ],
                    },
                ],
            },
        ],
    } as unknown as SourceConfigResponseApi,
}

const MIGRATION_ID = '01a1a3b0-0000-7000-8000-000000000001'
const ITEM_ID = '01a1a3b0-0000-7000-8000-000000000002'
const OTHER_ITEM_ID = '01a1a3b0-0000-7000-8000-000000000003'
const ITEM = {
    id: ITEM_ID,
    proposal: { prefill: { host: 'db.example.com', ssh_tunnel: { host: 'bastion.example.com' } } },
}

describe('sourceConnectSceneLogic', () => {
    let unmountAvailableSources: () => void
    let unmountLogic: () => void

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/external_data_sources/wizard/': AVAILABLE_SOURCES,
                '/api/projects/:team_id/warehouse_migrations/:id/items/:item_id/': ITEM,
            },
            post: {
                '/api/projects/:team_id/external_data_sources/store_credentials/': () => [
                    400,
                    { message: 'Could not connect to the database. Check the host, then try again.' },
                ],
            },
        })
        initKeaTests()
        unmountAvailableSources = availableSourcesLogic.mount()
        availableSourcesLogic.actions.loadSuccess(AVAILABLE_SOURCES)
        unmountLogic = sourceConnectSceneLogic.mount()
    })

    afterEach(() => {
        unmountLogic()
        unmountAvailableSources()
    })

    it.each([
        ['Postgres', 'Postgres'],
        ['postgres', 'Postgres'],
        ['HUBSPOT', 'Hubspot'],
    ])('resolves kind=%s to source config %s case-insensitively', (kind, expectedName) => {
        router.actions.push(`/data-warehouse/connect?kind=${kind}`)
        expect(sourceConnectSceneLogic.values.kind).toEqual(kind)
        expect(sourceConnectSceneLogic.values.sourceConfig?.name).toEqual(expectedName)
    })

    it('returns no source config for an unknown or missing kind', () => {
        router.actions.push('/data-warehouse/connect?kind=NotARealSource')
        expect(sourceConnectSceneLogic.values.sourceConfig).toBeNull()

        router.actions.push('/data-warehouse/connect')
        expect(sourceConnectSceneLogic.values.kind).toBeNull()
        expect(sourceConnectSceneLogic.values.sourceConfig).toBeNull()
    })

    it('starts with no stored credential and records one after setStoredCredential', () => {
        expect(sourceConnectSceneLogic.values.storedCredential).toBeNull()
        sourceConnectSceneLogic.actions.setStoredCredential({
            credential_id: 'ba07775f-8eaf-4d09-aa6f-50e37f17f243',
            source_type: 'Postgres',
            created_at: '2026-06-10T00:00:00Z',
            expires_at: '2026-06-11T00:00:00Z',
        })
        expect(sourceConnectSceneLogic.values.storedCredential?.credential_id).toEqual(
            'ba07775f-8eaf-4d09-aa6f-50e37f17f243'
        )
    })

    it('prefills a migration item once, without overwriting what the user typed', async () => {
        const url = `/data-warehouse/connect?kind=Postgres&migration_id=${MIGRATION_ID}&migration_item_id=${ITEM_ID}`
        await expectLogic(sourceConnectSceneLogic, () => router.actions.push(url)).toFinishAllListeners()
        expect(sourceConnectSceneLogic.values.migrationPrefillLoading).toBe(false)
        expect(sourceConnectSceneLogic.values.credentialsForm.payload).toEqual({
            host: 'db.example.com',
            ssh_tunnel: { host: 'bastion.example.com' },
        })

        sourceConnectSceneLogic.actions.setCredentialsFormValue(['payload', 'host'], 'typed.example.com')
        await expectLogic(sourceConnectSceneLogic, () =>
            sourceConnectSceneLogic.actions.loadMigrationPrefill(MIGRATION_ID, ITEM_ID)
        ).toFinishAllListeners()
        expect(sourceConnectSceneLogic.values.credentialsForm.payload.host).toEqual('typed.example.com')
    })

    it('ignores migration params that are not ids', async () => {
        const url = `/data-warehouse/connect?kind=Postgres&migration_id=../../other%3F&migration_item_id=${ITEM_ID}`
        await expectLogic(sourceConnectSceneLogic, () => router.actions.push(url))
            .toNotHaveDispatchedActions(['loadMigrationPrefill'])
            .toFinishAllListeners()
        expect(sourceConnectSceneLogic.values.credentialsForm.payload).toEqual({})
    })

    it('loads the prefill again after a failed request', async () => {
        const errorToast = jest.spyOn(lemonToast, 'error').mockReturnValue(undefined as any)
        useMocks({ get: { '/api/projects/:team_id/warehouse_migrations/:id/items/:item_id/': () => [500, {}] } })
        await expectLogic(sourceConnectSceneLogic, () =>
            sourceConnectSceneLogic.actions.loadMigrationPrefill(MIGRATION_ID, ITEM_ID)
        ).toFinishAllListeners()
        expect(errorToast).toHaveBeenCalled()
        expect(sourceConnectSceneLogic.values.migrationPrefillLoading).toBe(false)
        expect(sourceConnectSceneLogic.values.loadedMigrationItemId).toBeNull()

        useMocks({ get: { '/api/projects/:team_id/warehouse_migrations/:id/items/:item_id/': ITEM } })
        await expectLogic(sourceConnectSceneLogic, () =>
            sourceConnectSceneLogic.actions.loadMigrationPrefill(MIGRATION_ID, ITEM_ID)
        ).toFinishAllListeners()
        expect(sourceConnectSceneLogic.values.credentialsForm.payload.host).toEqual('db.example.com')
        errorToast.mockRestore()
    })

    it('keeps the prefill of the latest item when an earlier request finishes last', async () => {
        let releaseFirst: () => void = () => {}
        const firstReleased = new Promise<void>((resolve) => {
            releaseFirst = resolve
        })
        useMocks({
            get: {
                '/api/projects/:team_id/warehouse_migrations/:id/items/:item_id/': async (req) => {
                    if (req.params.item_id === ITEM_ID) {
                        await firstReleased
                        return [200, ITEM]
                    }
                    return [200, { id: OTHER_ITEM_ID, proposal: { prefill: { host: 'other.example.com' } } }]
                },
            },
        })
        sourceConnectSceneLogic.actions.loadMigrationPrefill(MIGRATION_ID, ITEM_ID)
        await expectLogic(sourceConnectSceneLogic, () =>
            sourceConnectSceneLogic.actions.loadMigrationPrefill(MIGRATION_ID, OTHER_ITEM_ID)
        ).toDispatchActions(['migrationPrefillLoaded'])
        releaseFirst()
        await expectLogic(sourceConnectSceneLogic).toFinishAllListeners()
        expect(sourceConnectSceneLogic.values.credentialsForm.payload.host).toEqual('other.example.com')
        expect(sourceConnectSceneLogic.values.loadedMigrationItemId).toEqual(OTHER_ITEM_ID)
    })

    it('shows the rejection message when the credentials fail validation', async () => {
        const errorToast = jest.spyOn(lemonToast, 'error').mockReturnValue(undefined as any)
        router.actions.push('/data-warehouse/connect?kind=Postgres')
        sourceConnectSceneLogic.actions.setCredentialsFormValue('payload', { host: 'db.example.com' })

        await expectLogic(sourceConnectSceneLogic, () => {
            sourceConnectSceneLogic.actions.submitCredentialsForm()
        }).toFinishAllListeners()

        expect(errorToast).toHaveBeenCalledWith('Could not connect to the database. Check the host, then try again.')
        expect(sourceConnectSceneLogic.values.storedCredential).toBeNull()
        errorToast.mockRestore()
    })
})
