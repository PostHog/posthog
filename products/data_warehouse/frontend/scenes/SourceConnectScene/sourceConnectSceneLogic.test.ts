import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

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

    it.each([
        ['another item', true],
        ['the plain connect page', false],
    ])('drops values typed for %s when a migration item opens', async (_name, fromItem) => {
        if (fromItem) {
            await expectLogic(sourceConnectSceneLogic, () =>
                sourceConnectSceneLogic.actions.loadMigrationPrefill(MIGRATION_ID, ITEM_ID)
            ).toFinishAllListeners()
        }
        sourceConnectSceneLogic.actions.setCredentialsFormValue(['payload', 'password'], 'typed-elsewhere')
        sourceConnectSceneLogic.actions.setStoredCredential({
            credential_id: 'ba07775f-8eaf-4d09-aa6f-50e37f17f243',
            source_type: 'Postgres',
            created_at: '2026-06-10T00:00:00Z',
            expires_at: '2026-06-11T00:00:00Z',
        })
        useMocks({
            get: {
                '/api/projects/:team_id/warehouse_migrations/:id/items/:item_id/': {
                    id: OTHER_ITEM_ID,
                    proposal: { prefill: { host: 'other.example.com' } },
                },
            },
        })

        await expectLogic(sourceConnectSceneLogic, () =>
            sourceConnectSceneLogic.actions.loadMigrationPrefill(MIGRATION_ID, OTHER_ITEM_ID)
        ).toFinishAllListeners()

        expect(sourceConnectSceneLogic.values.credentialsForm.payload).toEqual({ host: 'other.example.com' })
        expect(sourceConnectSceneLogic.values.storedCredential).toBeNull()
    })

    it('reloads an item after another item failed in between', async () => {
        jest.spyOn(lemonToast, 'error').mockReturnValue(undefined as any)
        await expectLogic(sourceConnectSceneLogic, () =>
            sourceConnectSceneLogic.actions.loadMigrationPrefill(MIGRATION_ID, ITEM_ID)
        ).toFinishAllListeners()
        useMocks({ get: { '/api/projects/:team_id/warehouse_migrations/:id/items/:item_id/': () => [500, {}] } })
        await expectLogic(sourceConnectSceneLogic, () =>
            sourceConnectSceneLogic.actions.loadMigrationPrefill(MIGRATION_ID, OTHER_ITEM_ID)
        ).toFinishAllListeners()

        useMocks({ get: { '/api/projects/:team_id/warehouse_migrations/:id/items/:item_id/': ITEM } })
        await expectLogic(sourceConnectSceneLogic, () =>
            sourceConnectSceneLogic.actions.loadMigrationPrefill(MIGRATION_ID, ITEM_ID)
        ).toFinishAllListeners()

        expect(sourceConnectSceneLogic.values.credentialsForm.payload.host).toEqual('db.example.com')
        jest.restoreAllMocks()
    })

    it('drops a pending prefill when the migration link is removed', async () => {
        let release: () => void = () => {}
        const released = new Promise<void>((resolve) => {
            release = resolve
        })
        useMocks({
            get: {
                '/api/projects/:team_id/warehouse_migrations/:id/items/:item_id/': async () => {
                    await released
                    return [200, ITEM]
                },
            },
        })
        router.actions.push(
            `/data-warehouse/connect?kind=Postgres&migration_id=${MIGRATION_ID}&migration_item_id=${ITEM_ID}`
        )
        router.actions.push('/data-warehouse/connect?kind=Postgres')
        release()
        await expectLogic(sourceConnectSceneLogic).toFinishAllListeners()

        expect(sourceConnectSceneLogic.values.credentialsForm.payload).toEqual({})
        expect(sourceConnectSceneLogic.values.migrationPrefillLoading).toBe(false)
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

    it('stores credentials for a prefilled item only once the server is confirmed, with the prefill kept', async () => {
        const bodies: Record<string, any>[] = []
        useMocks({
            post: {
                '/api/projects/:team_id/external_data_sources/store_credentials/': async ({ request }) => {
                    bodies.push((await request.json()) as Record<string, any>)
                    return [
                        201,
                        {
                            credential_id: 'ba07775f-8eaf-4d09-aa6f-50e37f17f243',
                            source_type: 'Postgres',
                            created_at: '2026-06-10T00:00:00Z',
                            expires_at: '2026-06-11T00:00:00Z',
                        },
                    ]
                },
            },
        })
        const url = `/data-warehouse/connect?kind=Postgres&migration_id=${MIGRATION_ID}&migration_item_id=${ITEM_ID}`
        await expectLogic(sourceConnectSceneLogic, () => router.actions.push(url)).toFinishAllListeners()
        expect(sourceConnectSceneLogic.values.prefilledFieldRows).toEqual([
            { label: 'Host', value: 'db.example.com' },
            { label: 'Ssh tunnel › Host', value: 'bastion.example.com' },
        ])
        // A changed prefilled value never reaches the API.
        sourceConnectSceneLogic.actions.setCredentialsFormValue(['payload', 'host'], 'elsewhere.example.com')

        await expectLogic(sourceConnectSceneLogic, () => {
            sourceConnectSceneLogic.actions.submitCredentialsForm()
        }).toFinishAllListeners()
        expect(bodies).toEqual([])

        sourceConnectSceneLogic.actions.setPrefillConfirmed(true)
        await expectLogic(sourceConnectSceneLogic, () => {
            sourceConnectSceneLogic.actions.submitCredentialsForm()
        }).toFinishAllListeners()
        expect(bodies).toEqual([
            {
                source_type: 'Postgres',
                payload: { host: 'db.example.com' },
                migration_item_id: ITEM_ID,
            },
        ])
        expect(sourceConnectSceneLogic.values.storedCredential).not.toBeNull()
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

    it.each([
        ['stored', 201, 'warehouse source connection saved', {}],
        ['rejected', 400, 'warehouse source connect failed', { error_class: 'rejected', status_code: 400 }],
        ['server error', 500, 'warehouse source connect failed', { error_class: 'server_error', status_code: 500 }],
    ])('tracks a %s submit from an agent link without what the user typed', async (_name, status, outcome, extra) => {
        jest.spyOn(lemonToast, 'error').mockReturnValue(undefined as any)
        jest.spyOn(posthog, 'captureException').mockReturnValue(undefined as any)
        const capture = jest.spyOn(posthog, 'capture')
        useMocks({
            post: {
                '/api/projects/:team_id/external_data_sources/store_credentials/': () => [
                    status,
                    status === 201
                        ? {
                              credential_id: 'ba07775f-8eaf-4d09-aa6f-50e37f17f243',
                              source_type: 'Postgres',
                              created_at: '2026-06-10T00:00:00Z',
                              expires_at: '2026-06-11T00:00:00Z',
                          }
                        : { message: 'Could not connect to db.example.com.' },
                ],
            },
        })
        router.actions.push('/data-warehouse/connect?kind=postgres&utm_source=wizard')
        sourceConnectSceneLogic.actions.setCredentialsFormValue('payload', { host: 'db.example.com' })

        await expectLogic(sourceConnectSceneLogic, () => {
            sourceConnectSceneLogic.actions.submitCredentialsForm()
        }).toFinishAllListeners()

        const linkProperties = { source_type: 'Postgres', link_source: 'wizard', from_migration: false }
        const connectCalls = capture.mock.calls.filter(([event]) =>
            String(event).startsWith('warehouse source connect')
        )
        expect(connectCalls).toEqual([
            ['warehouse source connect page viewed', linkProperties],
            ['warehouse source connect submitted', linkProperties],
            [outcome, { ...linkProperties, ...extra }],
        ])
        expect(JSON.stringify(connectCalls)).not.toContain('example.com')
        jest.restoreAllMocks()
    })
})
