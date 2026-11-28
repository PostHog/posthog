import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import * as dwApi from 'products/data_warehouse/frontend/generated/api'
import type { WarehouseStatusResponseApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { SettingsTab } from './SettingsTab'
import { warehouseProvisioningLogic } from './warehouseProvisioningLogic'
import { trinoStatusFixture, warehouseStatusFixture } from './warehouseStatusFixtures'

describe('SettingsTab', () => {
    const renderTab = (flags: string[]): void => {
        jest.spyOn(dwApi, 'dataWarehouseCheckSchemaNameRetrieve').mockResolvedValue({
            name: '',
            available: true,
        } as any)
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
        render(
            <Provider>
                <SettingsTab />
            </Provider>
        )
    }
    const renderWithStatus = (status: WarehouseStatusResponseApi, flags: string[]): void => {
        jest.spyOn(dwApi, 'dataWarehouseWarehouseStatusRetrieve').mockResolvedValue(status)
        renderTab(flags)
    }
    const renderWithFailedStatus = (error: { status: number }, flags: string[]): void => {
        jest.spyOn(dwApi, 'dataWarehouseWarehouseStatusRetrieve').mockRejectedValue(error)
        renderTab(flags)
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('shows the Trino connection and no Postgres details for a Trino organization', async () => {
        renderWithStatus(
            warehouseStatusFixture({
                state: 'ready',
                status_message: '',
                ready_at: '2026-08-01T12:00:00Z',
                connection: null,
                team_onboarded: true,
                schema_name: 'analytics',
                trino: {
                    state: 'ready',
                    ready_at: '2026-09-01T12:00:00Z',
                    hoglake: false,
                    connection: {
                        host: 'my-warehouse.dw.example.com',
                        port: 443,
                        catalog: 'org_my_warehouse',
                        username: 'root',
                    },
                },
            }),
            [FEATURE_FLAGS.MANAGED_TRINO_QUERY]
        )

        expect(await screen.findByText('Catalog')).toBeInTheDocument()
        // CodeSnippet can split its text across elements, so these read the page text.
        const pageText = document.body.textContent ?? ''
        expect(pageText).toContain('--catalog org_my_warehouse --schema analytics')
        expect(pageText).not.toMatch(/psql|ducklake/i)
    })

    describe('hoglake credentials', () => {
        const trinoOrg = (hoglake: boolean): WarehouseStatusResponseApi =>
            warehouseStatusFixture({
                state: 'ready',
                connection: null,
                trino: trinoStatusFixture({
                    hoglake,
                    connection: { host: 'my-warehouse.dw.example.com', port: 443, catalog: 'org_x', username: 'root' },
                }),
            })
        const credentialLists = (): jest.SpyInstance[] => [
            jest.spyOn(dwApi, 'dataWarehouseHoglakeCredentialsRetrieve').mockResolvedValue({
                hoglake_credentials: [],
            } as any),
            jest.spyOn(dwApi, 'dataWarehouseMyHoglakeCredentialsRetrieve').mockResolvedValue({
                hoglake_credentials: [],
                projects: [],
            } as any),
        ]

        it('shows them for a hoglake catalog', async () => {
            const lists = credentialLists()
            renderWithStatus(trinoOrg(true), [FEATURE_FLAGS.MANAGED_TRINO_QUERY])

            expect(await screen.findByText('Hoglake credentials')).toBeInTheDocument()
            expect(await screen.findByText('Your hoglake credentials')).toBeInTheDocument()
            lists.forEach((list) => expect(list).toHaveBeenCalled())
        })

        it('leaves them out for a DuckLake catalog, where they would reach nothing', async () => {
            const lists = credentialLists()
            renderWithStatus(trinoOrg(false), [FEATURE_FLAGS.MANAGED_TRINO_QUERY])

            expect(await screen.findByText('Catalog')).toBeInTheDocument()
            expect(screen.queryByText('Hoglake credentials')).not.toBeInTheDocument()
            expect(screen.queryByText('Your hoglake credentials')).not.toBeInTheDocument()
            lists.forEach((list) => expect(list).not.toHaveBeenCalled())
        })
    })

    it('keeps the Postgres connection for a DuckDB organization', async () => {
        renderWithStatus(
            warehouseStatusFixture({
                state: 'ready',
                status_message: '',
                ready_at: '2026-08-01T12:00:00Z',
                connection: { host: 'my-warehouse.dw.example.com', port: 5432, database: 'ducklake', username: 'root' },
                team_onboarded: true,
                schema_name: 'analytics',
                trino: null,
            }),
            [FEATURE_FLAGS.DATA_WAREHOUSE_SCENE]
        )

        expect(await screen.findByText('Connect with psql')).toBeInTheDocument()
        expect(screen.queryByText('Catalog')).not.toBeInTheDocument()
    })

    const duckdbConnection = {
        host: 'my-warehouse.dw.example.com',
        port: 5432,
        database: 'ducklake',
        username: 'root',
    }

    it('says the join state is unknown instead of offering to enable the project', async () => {
        renderWithStatus(
            warehouseStatusFixture({ connection: duckdbConnection, team_onboarded: null, schema_name: null }),
            [FEATURE_FLAGS.DATA_WAREHOUSE_SCENE]
        )

        expect(
            await screen.findByText("Couldn't check whether this project has joined the warehouse. Retrying...")
        ).toBeInTheDocument()
        expect(screen.queryByText('Enable this project')).not.toBeInTheDocument()
    })

    it('warns that the page is out of date when a refresh fails, and keeps the last status', async () => {
        jest.spyOn(dwApi, 'dataWarehouseWarehouseStatusRetrieve')
            .mockResolvedValueOnce(warehouseStatusFixture({ connection: duckdbConnection }))
            .mockRejectedValue({ status: 500 })
        renderTab([FEATURE_FLAGS.DATA_WAREHOUSE_SCENE])
        await screen.findByText('Connect with psql')

        warehouseProvisioningLogic.actions.loadWarehouseStatus()

        expect(
            await screen.findByText("Couldn't refresh the warehouse status, so this page may be out of date.")
        ).toBeInTheDocument()
        expect(screen.getByText('Connect with psql')).toBeInTheDocument()
    })

    it('offers a retry instead of the setup form when the status fails to load', async () => {
        renderWithFailedStatus({ status: 500 }, [FEATURE_FLAGS.DATA_WAREHOUSE_SCENE])

        expect(await screen.findByText('Try again')).toBeInTheDocument()
        expect(screen.queryByText('Provision warehouse')).not.toBeInTheDocument()
    })

    describe.each([
        { name: 'an admin', level: OrganizationMembershipLevel.Admin },
        { name: 'a member', level: OrganizationMembershipLevel.Member },
    ])('as $name', ({ level }) => {
        beforeEach(() => {
            initKeaTests(true, undefined, undefined, { ...MOCK_DEFAULT_ORGANIZATION, membership_level: level })
        })

        it('only offers provisioning to admins', async () => {
            renderWithFailedStatus({ status: 404 }, [FEATURE_FLAGS.DATA_WAREHOUSE_SCENE])

            const isAdmin = level === OrganizationMembershipLevel.Admin
            await screen.findByText(isAdmin ? 'Warehouse name' : "Your organization doesn't have a warehouse yet")
            expect(screen.queryAllByText('Provision warehouse')).toHaveLength(isAdmin ? 1 : 0)
            expect(screen.queryAllByText(/Only organization admins can provision it/)).toHaveLength(isAdmin ? 0 : 1)
        })

        it('only enables password reset for admins', async () => {
            renderWithStatus(
                warehouseStatusFixture({
                    connection: {
                        host: 'my-warehouse.dw.example.com',
                        port: 5432,
                        database: 'ducklake',
                        username: 'root',
                    },
                    trino: null,
                }),
                [FEATURE_FLAGS.DATA_WAREHOUSE_SCENE]
            )

            const button = (await screen.findByText('Reset password')).closest('button')
            expect(button).toHaveAttribute(
                'aria-disabled',
                level === OrganizationMembershipLevel.Admin ? 'false' : 'true'
            )
        })
    })
})
