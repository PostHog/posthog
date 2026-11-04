import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { postgreSQLSetupModalLogic } from 'scenes/integrations/postgresql/postgreSQLSetupModalLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { destinationConnectSceneLogic } from './destinationConnectSceneLogic'

const ITEMS: Record<string, Record<string, any>> = {
    'item-1': {
        id: 'item-1',
        created_by: { first_name: 'Ana', email: 'ana@example.com' },
        proposal: {
            prefix: 'shop',
            destination: {
                type: 'Postgres',
                config: {
                    host: 'db.example.com',
                    port: 6543,
                    user: 'loader',
                    database: 'analytics',
                    connection_type: 'Directly',
                },
            },
        },
    },
    'item-2': {
        id: 'item-2',
        proposal: {
            prefix: 'billing',
            destination: { type: 'Postgres', config: { host: 'billing.example.com' } },
        },
    },
}

describe('destinationConnectSceneLogic', () => {
    let unmountLogic: () => void
    let itemRequests: number

    beforeEach(() => {
        itemRequests = 0
        useMocks({
            get: {
                '/api/projects/:team_id/warehouse_migrations/:id/items/:item_id/': ({ params }) => {
                    itemRequests += 1
                    const item = ITEMS[params.item_id as string]
                    return item ? [200, item] : [404, { detail: 'Not found.' }]
                },
            },
        })
        initKeaTests()
        jest.spyOn(posthog, 'capture')
        unmountLogic = destinationConnectSceneLogic.mount()
    })

    afterEach(() => {
        unmountLogic()
        jest.restoreAllMocks()
    })

    it.each([
        ['?kind=snowflake', 'Snowflake'],
        ['?kind=s3-compatible', 'S3'],
        ['?kind=twilio', null],
        ['', null],
    ])('resolves %s to destination type %s and tracks only a supported kind', (search, expectedType) => {
        router.actions.push(`/data-warehouse/connect-destination${search}`)

        expect(destinationConnectSceneLogic.values.destinationDefinition?.type ?? null).toEqual(expectedType)
        const viewed = (posthog.capture as jest.Mock).mock.calls.filter(
            ([event]) => event === 'warehouse destination connect page viewed'
        )
        expect(viewed).toHaveLength(expectedType ? 1 : 0)
    })

    it('keeps the saved connection when only the hash changes', () => {
        router.actions.push('/data-warehouse/connect-destination?kind=snowflake')
        destinationConnectSceneLogic.actions.setIntegrationId(42)

        router.actions.replace('/data-warehouse/connect-destination', { kind: 'snowflake' }, { panel: 'max' })

        expect(destinationConnectSceneLogic.values.integrationId).toEqual(42)
        const viewed = (posthog.capture as jest.Mock).mock.calls.filter(
            ([event]) => event === 'warehouse destination connect page viewed'
        )
        expect(viewed).toHaveLength(1)
    })

    it('locks the prefilled server, opens the form only after the user confirms it, and saves the locked values', async () => {
        const created: Record<string, any>[] = []
        useMocks({
            post: {
                '/api/projects/:team_id/integrations': async ({ request }) => {
                    created.push((await request.json()) as Record<string, any>)
                    return [201, { id: 7, kind: 'postgresql' }]
                },
            },
        })
        const searchParams = { kind: 'postgresql', migration_id: 'migration-1', migration_item_id: 'item-1' }
        await expectLogic(destinationConnectSceneLogic, () =>
            router.actions.push('/data-warehouse/connect-destination', searchParams)
        ).toFinishAllListeners()
        router.actions.replace('/data-warehouse/connect-destination', searchParams, { panel: 'max' })
        await expectLogic(destinationConnectSceneLogic).toFinishAllListeners()

        expect(itemRequests).toEqual(1)
        expect(destinationConnectSceneLogic.values).toMatchObject({
            migrationCreator: { first_name: 'Ana', email: 'ana@example.com' },
            prefilledFieldRows: [
                { label: 'Host', value: 'db.example.com' },
                { label: 'Port', value: '6543' },
                { label: 'User', value: 'loader' },
            ],
            setupModalOpen: false,
            openSetupDisabledReason: 'Confirm the server above first',
        })
        destinationConnectSceneLogic.actions.setPrefillConfirmed(true)
        expect(destinationConnectSceneLogic.values.setupModalOpen).toBe(true)

        const formLogic = postgreSQLSetupModalLogic({
            isOpen: true,
            locked: { values: destinationConnectSceneLogic.values.lockedSetupValues!, reason: 'Set by the migration.' },
            onComplete: () => {},
        })
        formLogic.mount()
        expect(formLogic.values.postgreSQLIntegration).toMatchObject({
            host: 'db.example.com',
            port: 6543,
            user: 'loader',
            password: null,
        })
        expect(formLogic.values.postgreSQLIntegration).not.toHaveProperty('database')
        formLogic.actions.setPostgreSQLIntegrationValues({
            host: 'elsewhere.example.net',
            password: 'not-a-real-secret',
        })
        await expectLogic(formLogic, () => formLogic.actions.submitPostgreSQLIntegration()).toFinishAllListeners()
        expect(created).toHaveLength(1)
        expect(created[0].config).toMatchObject({ host: 'db.example.com', port: 6543, user: 'loader' })
        formLogic.unmount()
    })

    it('follows the latest migration item link and drops the connection saved for the previous one', async () => {
        const open = (itemId: string): void =>
            router.actions.push('/data-warehouse/connect-destination', {
                kind: 'postgresql',
                migration_id: 'migration-1',
                migration_item_id: itemId,
            })
        await expectLogic(destinationConnectSceneLogic, () => {
            open('item-1')
            open('item-2')
        }).toFinishAllListeners()
        expect(destinationConnectSceneLogic.values.lockedSetupValues).toEqual({ host: 'billing.example.com' })

        destinationConnectSceneLogic.actions.setPrefillConfirmed(true)
        destinationConnectSceneLogic.actions.setIntegrationId(42)
        await expectLogic(destinationConnectSceneLogic, () => open('item-1')).toFinishAllListeners()

        expect(destinationConnectSceneLogic.values).toMatchObject({
            integrationId: null,
            prefillConfirmed: false,
            isModalOpen: true,
            lockedSetupValues: { host: 'db.example.com', port: 6543, user: 'loader' },
        })
    })

    it('drops migration settings on a plain link and ignores a save from the previous item', async () => {
        const open = (itemId?: string): void =>
            router.actions.push('/data-warehouse/connect-destination', {
                kind: 'postgresql',
                ...(itemId ? { migration_id: 'migration-1', migration_item_id: itemId } : {}),
            })
        await expectLogic(destinationConnectSceneLogic, () => {
            open('item-1')
            open()
        }).toFinishAllListeners()
        expect(destinationConnectSceneLogic.values).toMatchObject({
            migrationItemId: null,
            lockedSetupValues: undefined,
        })

        await expectLogic(destinationConnectSceneLogic, () => open('item-2')).toFinishAllListeners()
        destinationConnectSceneLogic.actions.completeSetup(42, 'item-1')
        expect(destinationConnectSceneLogic.values.integrationId).toBeNull()
        destinationConnectSceneLogic.actions.completeSetup(43, 'item-2')
        expect(destinationConnectSceneLogic.values.integrationId).toEqual(43)
    })

    it.each([
        { search: '?kind=snowflake&token=abc_123', status: 200, expected: 'sent', requested: true },
        { search: '?kind=snowflake&token=abc_123', status: 404, expected: 'failed', requested: true },
        { search: '?kind=snowflake', status: 200, expected: null, requested: false },
    ])(
        'hands the saved connection back for $search when the API returns $status',
        async ({ search, status, expected, requested }) => {
            const requests: unknown[] = []
            useMocks({
                post: {
                    '/api/projects/:team_id/external_data_destinations/connect_link_complete/': async ({ request }) => {
                        requests.push(await request.json())
                        return [status, {}]
                    },
                },
            })
            router.actions.push(`/data-warehouse/connect-destination${search}`)

            await expectLogic(destinationConnectSceneLogic, () => {
                destinationConnectSceneLogic.actions.setIntegrationId(42)
            }).toFinishAllListeners()

            expect(destinationConnectSceneLogic.values.handBackStatus).toEqual(expected)
            expect(requests).toEqual(requested ? [{ connect_token: 'abc_123', integration_id: 42 }] : [])
        }
    )
})
