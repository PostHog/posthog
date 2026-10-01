import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import * as dwApi from 'products/data_warehouse/frontend/generated/api'

import { SettingsTab } from './SettingsTab'

describe('SettingsTab', () => {
    const renderWithStatus = (status: Record<string, unknown>, flags: string[]): void => {
        jest.spyOn(dwApi, 'dataWarehouseWarehouseStatusRetrieve').mockResolvedValue(status as any)
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
            {
                state: 'ready',
                status_message: '',
                ready_at: '2026-08-01T12:00:00Z',
                connection: null,
                team_onboarded: true,
                schema_name: 'analytics',
                trino: {
                    state: 'ready',
                    ready_at: '2026-09-01T12:00:00Z',
                    connection: {
                        host: 'my-warehouse.dw.example.com',
                        port: 443,
                        catalog: 'org_my_warehouse',
                        username: 'root',
                    },
                },
            },
            [FEATURE_FLAGS.DATA_WAREHOUSE_SCENE_TRINO]
        )

        expect(await screen.findByText('Catalog')).toBeInTheDocument()
        // CodeSnippet can split its text across elements, so these read the page text.
        const pageText = document.body.textContent ?? ''
        expect(pageText).toContain('jdbc:trino://my-warehouse.dw.example.com:443/org_my_warehouse/analytics?SSL=true')
        expect(pageText).toContain('--catalog org_my_warehouse --schema analytics')
        expect(pageText).not.toMatch(/psql|ducklake/i)
    })

    it('keeps the Postgres connection for a DuckDB organization', async () => {
        renderWithStatus(
            {
                state: 'ready',
                status_message: '',
                ready_at: '2026-08-01T12:00:00Z',
                connection: { host: 'my-warehouse.dw.example.com', port: 5432, database: 'ducklake', username: 'root' },
                team_onboarded: true,
                schema_name: 'analytics',
                trino: null,
            },
            [FEATURE_FLAGS.DATA_WAREHOUSE_SCENE]
        )

        expect(await screen.findByText('Connect with psql')).toBeInTheDocument()
        expect(screen.queryByText('Catalog')).not.toBeInTheDocument()
    })
})
