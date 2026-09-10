import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import api from 'lib/api'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { dataWarehouseSettingsSceneLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsSceneLogic'

import { useMocks } from '~/mocks/jest'
import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, DataWarehouseTable } from '~/types'

import { SelfManagedColumnsSection } from './SelfManagedColumnsSection'

jest.mock('~/queries/query')

const SCHEMA = {
    tables: {
        orders_csv: {
            id: 'table-1',
            name: 'orders_csv',
            type: 'data_warehouse',
            fields: {
                total: { name: 'total', hogql_value: 'total', type: 'string', schema_valid: true },
            },
        },
        refunds_csv: {
            id: 'table-2',
            name: 'refunds_csv',
            type: 'data_warehouse',
            fields: {
                total: { name: 'total', hogql_value: 'total', type: 'string', schema_valid: true },
            },
        },
    },
    joins: [],
}

// What a lazy schema load leaves in the store: table names and metadata, no fields.
const SHALLOW_SCHEMA = {
    tables: {
        orders_csv: { ...SCHEMA.tables.orders_csv, fields: {} },
        refunds_csv: { ...SCHEMA.tables.refunds_csv, fields: {} },
    },
    joins: [],
}

const TABLE: DataWarehouseTable = {
    id: 'table-1',
    name: 'orders_csv',
    format: 'CSV',
    url_pattern: 'https://example.com/orders/*.csv',
    credential: null,
    user_access_level: AccessControlLevel.Editor,
}

const OTHER_TABLE: DataWarehouseTable = {
    ...TABLE,
    id: 'table-2',
    name: 'refunds_csv',
    url_pattern: 'https://example.com/refunds/*.csv',
}

describe('SelfManagedColumnsSection', () => {
    let updateSchema: jest.SpyInstance
    // Releasing this in `afterEach` too keeps a failed in-flight assertion from leaving the schema
    // query pending for the tests that follow.
    let releaseSchemaQuery: (response: unknown) => void

    beforeEach(() => {
        releaseSchemaQuery = () => {}
        useMocks({ get: { '/api/environments/:team_id/warehouse_saved_queries/': { results: [] } } })
        initKeaTests()
        ;(performQuery as jest.Mock).mockResolvedValue(SCHEMA)
        updateSchema = jest.spyOn(api.dataWarehouseTables, 'updateSchema').mockResolvedValue(undefined)
    })

    afterEach(() => {
        releaseSchemaQuery(SCHEMA)
        cleanup()
        jest.restoreAllMocks()
    })

    it('offers the column type editor and saves the new type through the warehouse table API', async () => {
        render(<SelfManagedColumnsSection table={TABLE} />)

        // Read-only until asked: the type reads as a tag, with no control to change it.
        await waitFor(() => expect(screen.getByText('total')).toBeInTheDocument())
        expect(screen.queryByRole('button', { name: 'String' })).not.toBeInTheDocument()

        await userEvent.click(screen.getByRole('button', { name: 'Edit column types' }))

        await userEvent.click(screen.getByRole('button', { name: 'String' }))
        // The types PostHog cannot store are not on offer.
        expect(await screen.findByText('Integer')).toBeInTheDocument()
        expect(screen.queryByText('Unknown')).not.toBeInTheDocument()
        expect(screen.queryByText('Array')).not.toBeInTheDocument()
        expect(screen.queryByText('JSON')).not.toBeInTheDocument()

        await userEvent.click(screen.getByText('Integer'))
        await userEvent.click(screen.getByRole('button', { name: 'Save types' }))

        await waitFor(() => expect(updateSchema).toHaveBeenCalledWith('table-1', { total: 'integer' }))
    })

    it('locks the type dropdowns while a save is in flight', async () => {
        let releaseSave = (): void => {}
        updateSchema.mockReturnValue(
            new Promise<void>((resolve) => {
                releaseSave = () => resolve()
            })
        )

        render(<SelfManagedColumnsSection table={TABLE} />)
        await waitFor(() => expect(screen.getByText('total')).toBeInTheDocument())

        await userEvent.click(screen.getByRole('button', { name: 'Edit column types' }))
        await userEvent.click(screen.getByRole('button', { name: 'String' }))
        await userEvent.click(await screen.findByText('Integer'))
        await userEvent.click(screen.getByRole('button', { name: 'Save types' }))

        // The save reads the pending types once, so a type picked after it starts is dropped by
        // the refresh that follows.
        await waitFor(() =>
            expect(screen.getByRole('button', { name: 'Integer' })).toHaveAttribute('aria-disabled', 'true')
        )

        releaseSave()
    })

    it('drops an abandoned type change when the edit is canceled', async () => {
        render(<SelfManagedColumnsSection table={TABLE} />)
        await waitFor(() => expect(screen.getByText('total')).toBeInTheDocument())

        await userEvent.click(screen.getByRole('button', { name: 'Edit column types' }))
        await userEvent.click(screen.getByRole('button', { name: 'String' }))
        await userEvent.click(await screen.findByText('Integer'))
        await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))

        // The pending type is held on the same object as the shared schema store, which the SQL
        // editor's schema tree and the taxonomic filters read too.
        expect(databaseTableListLogic.values.database?.tables.orders_csv.fields.total.type).toEqual('string')

        await userEvent.click(screen.getByRole('button', { name: 'Edit column types' }))
        expect(screen.getByRole('button', { name: 'String' })).toBeInTheDocument()
        expect(updateSchema).not.toHaveBeenCalled()
    })

    it('drops a pending type change when the page moves to another table', async () => {
        const { rerender } = render(<SelfManagedColumnsSection table={TABLE} />)
        await waitFor(() => expect(screen.getByText('total')).toBeInTheDocument())

        await userEvent.click(screen.getByRole('button', { name: 'Edit column types' }))
        await userEvent.click(screen.getByRole('button', { name: 'String' }))
        await userEvent.click(await screen.findByText('Integer'))

        // Both source pages are the same scene, so moving between them hands this section a new
        // table without unmounting it. Both tables have a `total` column, which is what lets a
        // pending type reach the wrong one.
        rerender(<SelfManagedColumnsSection table={OTHER_TABLE} />)

        expect(await screen.findByRole('button', { name: 'Edit column types' })).toBeInTheDocument()
        await userEvent.click(screen.getByRole('button', { name: 'Edit column types' }))
        await userEvent.click(screen.getByRole('button', { name: 'Save types' }))

        expect(updateSchema).not.toHaveBeenCalled()
    })

    it('shows the columns when the schema store hydrates the table after mount', async () => {
        ;(performQuery as jest.Mock).mockResolvedValueOnce(SHALLOW_SCHEMA)
        databaseTableListLogic.mount()
        await databaseTableListLogic.asyncActions.loadDatabase({ shallow: true })

        render(<SelfManagedColumnsSection table={TABLE} />)

        // The section starts on a fields-less table, and hydration replaces that table object
        // instead of reloading the whole schema.
        expect(await screen.findByText('total')).toBeInTheDocument()
    })

    it('recovers from a failed schema query through the retry', async () => {
        ;(performQuery as jest.Mock).mockRejectedValue(new Error('schema query failed'))

        render(<SelfManagedColumnsSection table={TABLE} />)

        expect(await screen.findByText("Couldn't load this table's columns.")).toBeInTheDocument()

        ;(performQuery as jest.Mock).mockResolvedValue(SCHEMA)
        // LemonBanner renders its action twice, once for each width.
        await userEvent.click(screen.getAllByText('Try again')[0])

        await waitFor(() => expect(screen.getByText('total')).toBeInTheDocument())
    })

    it('keeps the columns behind a skeleton while a refresh is in flight', async () => {
        render(<SelfManagedColumnsSection table={TABLE} />)
        await waitFor(() => expect(screen.getByText('total')).toBeInTheDocument())

        ;(performQuery as jest.Mock).mockReturnValue(
            new Promise((resolve) => {
                releaseSchemaQuery = resolve
            })
        )
        dataWarehouseSettingsSceneLogic.actions.refreshDatabaseSchema()

        // The schema store reports no tables for the whole of a load, so the no-columns message
        // would otherwise tell the user to check their credentials after every save.
        await waitFor(() => expect(screen.queryByText('total')).not.toBeInTheDocument())
        expect(screen.queryByText(/hasn't read this table's columns yet/)).not.toBeInTheDocument()

        releaseSchemaQuery(SCHEMA)
        await waitFor(() => expect(screen.getByText('total')).toBeInTheDocument())
    })

    it('disables the editor for a viewer', async () => {
        render(<SelfManagedColumnsSection table={{ ...TABLE, user_access_level: AccessControlLevel.Viewer }} />)

        await waitFor(() => expect(screen.getByText('total')).toBeInTheDocument())
        expect(screen.getByRole('button', { name: 'Edit column types' })).toHaveAttribute('aria-disabled', 'true')
    })
})
