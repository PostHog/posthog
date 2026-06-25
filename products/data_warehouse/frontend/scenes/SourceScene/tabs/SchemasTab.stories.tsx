import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { useStorybookMocks } from '~/mocks/browser'
import externalDataSourceResponseMock from '~/mocks/fixtures/api/projects/team_id/external_data_sources/externalDataSource.json'

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
        featureFlags: [FEATURE_FLAGS.REVENUE_ANALYTICS],
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
