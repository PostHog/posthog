import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import * as dwApi from 'products/data_warehouse/frontend/generated/api'
import type { WarehouseStatusResponseApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { SettingsTab } from './SettingsTab'
import { trinoStatusFixture, warehouseStatusFixture } from './warehouseStatusFixtures'

describe('SettingsTab', () => {
    const renderWithStatus = (status: WarehouseStatusResponseApi, flags: string[]): void => {
        jest.spyOn(dwApi, 'dataWarehouseWarehouseStatusRetrieve').mockResolvedValue(status)
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
})
