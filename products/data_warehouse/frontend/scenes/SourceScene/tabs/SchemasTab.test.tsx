import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, ExternalDataSourceSchema } from '~/types'

import { SchemaRowMore } from './SchemasTab'

const makeSchema = (overrides: Partial<ExternalDataSourceSchema> = {}): ExternalDataSourceSchema => ({
    id: 'schema-1',
    name: 'public.events',
    label: null,
    should_sync: true,
    incremental: false,
    sync_type: 'full_refresh',
    sync_time_of_day: null,
    latest_error: null,
    incremental_field: null,
    incremental_field_type: null,
    sync_frequency: '6hour',
    primary_key_columns: null,
    user_access_level: AccessControlLevel.Editor,
    ...overrides,
})

const rowMenu = (schema: ExternalDataSourceSchema): JSX.Element => (
    <SchemaRowMore
        source={null}
        schema={schema}
        reloadSchema={jest.fn()}
        resyncSchema={jest.fn()}
        cancelSchema={jest.fn()}
        deleteTable={jest.fn()}
    />
)

describe('SchemaRowMore', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('keeps the menu open when a poll re-renders the row with a fresh schema object', () => {
        const schema = makeSchema()
        const { rerender } = render(rowMenu(schema))
        fireEvent.click(screen.getByLabelText('more'))
        expect(screen.getByText('Sync now')).toBeInTheDocument()

        rerender(rowMenu({ ...schema }))

        expect(screen.getByText('Sync now')).toBeInTheDocument()
    })

    it('closes and disables the menu when a poll revokes editor access', () => {
        const schema = makeSchema()
        const { rerender } = render(rowMenu(schema))
        fireEvent.click(screen.getByLabelText('more'))
        expect(screen.getByText('Sync now')).toBeInTheDocument()

        rerender(rowMenu({ ...schema, user_access_level: AccessControlLevel.Viewer }))

        expect(screen.queryByText('Sync now')).not.toBeInTheDocument()
        expect(screen.getByLabelText('more')).toHaveAttribute('aria-disabled', 'true')
    })
})
