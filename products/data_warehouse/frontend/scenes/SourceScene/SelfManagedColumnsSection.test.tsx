import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import api from 'lib/api'
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
        // Saving a column as Unknown fails, so the type PostHog can't store is not on offer.
        expect(await screen.findByText('Integer')).toBeInTheDocument()
        expect(screen.queryByText('Unknown')).not.toBeInTheDocument()

        await userEvent.click(screen.getByText('Integer'))
        await userEvent.click(screen.getByRole('button', { name: 'Save types' }))

        await waitFor(() => expect(updateSchema).toHaveBeenCalledWith('table-1', { total: 'integer' }))
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
