import type { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'

import { useStorybookMocks } from '~/mocks/browser'
import externalDataSourceResponseMock from '~/mocks/fixtures/api/projects/team_id/external_data_sources/externalDataSource.json'

import { expect, userEvent } from 'storybook/test'

import { SchemasTab, SchemasTabProps } from './SchemasTab'

type Story = StoryObj<SchemasTabProps>
const meta: Meta<SchemasTabProps> = {
    title: 'Scenes-App/Data Warehouse/Settings/Schemas',
    component: SchemasTab,
    args: {
        id: '123',
    },
    parameters: {
        mockDate: '2023-02-01',
        viewMode: 'story',
        testOptions: {
            snapshotBrowsers: ['chromium'],
        },
    },
    render: (props) => {
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/external_data_sources/:id': () => {
                    return [200, externalDataSourceResponseMock]
                },
            },
        })

        return <SchemasTab {...props} />
    },
}

export default meta

export const Default: Story = {
    args: {},
}

// Multi-schema SQL source: qualified `namespace.table` schema names spanning two
// namespaces, including the same table name in both, rendered as collapsible groups.
const MULTI_SCHEMA_TABLE_NAMES = ['dbo.users', 'dbo.orders', 'dbo.invoices', 'sales.users', 'sales.leads']

const multiSchemaSourceMock = {
    ...externalDataSourceResponseMock,
    source_type: 'MSSQL',
    prefix: 'mssql_',
    job_inputs: { schema: '' },
    schemas: externalDataSourceResponseMock.schemas
        .slice(0, MULTI_SCHEMA_TABLE_NAMES.length)
        .map((schema, index) => ({ ...schema, name: MULTI_SCHEMA_TABLE_NAMES[index] })),
}

export const MultiSchema: Story = {
    render: (props) => {
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/external_data_sources/:id': () => {
                    return [200, multiSchemaSourceMock]
                },
            },
        })

        return <SchemasTab {...props} />
    },
}

// A table a sync run proved can't merge: it is disabled, and its sync method carries the reason.
const blockedSchemaSourceMock = {
    ...externalDataSourceResponseMock,
    schemas: externalDataSourceResponseMock.schemas.map((schema, index) =>
        index === 1
            ? {
                  ...schema,
                  should_sync: false,
                  status: 'Failed',
                  sync_type: 'incremental',
                  incremental_sync_blocked: 'duplicate_primary_key',
              }
            : schema
    ),
}

export const IncrementalSyncBlocked: Story = {
    render: (props) => {
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/external_data_sources/:id': () => {
                    return [200, blockedSchemaSourceMock]
                },
            },
        })

        return <SchemasTab {...props} />
    },
}

const objectStorageSourceMock = {
    ...externalDataSourceResponseMock,
    source_type: 'AmazonS3',
    prefix: 's3_',
    job_inputs: { url_pattern: 's3://my-bucket/events/*.parquet' },
    supports_adding_tables: true,
    table_root: 'my-bucket/events/',
    supports_table_discovery: true,
}

const objectStorageParameters = { featureFlags: [FEATURE_FLAGS.WAREHOUSE_OBJECT_STORAGE_ADD_TABLE] }

function renderWithSource(source: Record<string, any>): NonNullable<Story['render']> {
    return (props) => {
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/external_data_sources/:id': () => [200, source],
            },
        })

        return <SchemasTab {...props} />
    }
}

// Object storage sources replace "Pull new schemas" with "Add table", and keep discovery in its menu.
export const ObjectStorage: Story = {
    parameters: objectStorageParameters,
    render: renderWithSource(objectStorageSourceMock),
}

// A migrated source reads the whole bucket, so it gets Add table without the flag and has no discovery menu.
export const ObjectStorageMigrated: Story = {
    render: renderWithSource({ ...objectStorageSourceMock, supports_table_discovery: false }),
}

export const AddTableModalOpen: Story = {
    parameters: objectStorageParameters,
    render: renderWithSource(objectStorageSourceMock),
    play: async ({ canvasElement }) => {
        const body = within(canvasElement.ownerDocument.body)
        await waitFor(async () => {
            if (!body.queryByText('Enter a path inside', { exact: false })) {
                const button = canvasElement.querySelector<HTMLElement>('[data-attr="schemas-tab-add-table"]')
                expect(button).toBeVisible()
                await userEvent.click(button!)
            }
            expect(body.getByText('Enter a path inside', { exact: false })).toBeVisible()
        })
    },
}
