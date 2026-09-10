import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, DataWarehouseTable } from '~/types'

import { SelfManagedColumnsSection } from './SelfManagedColumnsSection'

jest.mock('~/queries/query')

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

    beforeEach(() => {
        useMocks({ get: { '/api/environments/:team_id/warehouse_saved_queries/': { results: [] } } })
        initKeaTests()
        ;(performQuery as jest.Mock).mockResolvedValue({
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
        })
        updateSchema = jest.spyOn(api.dataWarehouseTables, 'updateSchema').mockResolvedValue(undefined)
    })

    afterEach(() => {
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
        await userEvent.click(await screen.findByText('Integer'))
        await userEvent.click(screen.getByRole('button', { name: 'Save types' }))

        await waitFor(() => expect(updateSchema).toHaveBeenCalledWith('table-1', { total: 'integer' }))
    })

    it('disables the editor for a viewer', async () => {
        render(<SelfManagedColumnsSection table={{ ...TABLE, user_access_level: AccessControlLevel.Viewer }} />)

        await waitFor(() => expect(screen.getByText('total')).toBeInTheDocument())
        expect(screen.getByRole('button', { name: 'Edit column types' })).toHaveAttribute('aria-disabled', 'true')
    })
})
