import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import { AccessControlLevel, DataWarehouseTable } from '~/types'

import { SelfManagedColumnsSection } from './SelfManagedColumnsSection'

const TABLE: DataWarehouseTable = {
    id: 'table-1',
    name: 'orders_csv',
    format: 'CSV',
    url_pattern: 'https://example.com/orders/*.csv',
    credential: null,
    user_access_level: AccessControlLevel.Editor,
}

const DATABASE_SCHEMA = {
    tables: {
        orders_csv: {
            id: 'table-1',
            name: 'orders_csv',
            type: 'data_warehouse',
            fields: {
                order_id: { name: 'order_id', hogql_value: 'order_id', type: 'string', schema_valid: true },
                total: { name: 'total', hogql_value: 'total', type: 'string', schema_valid: true },
                ordered_at: { name: 'ordered_at', hogql_value: 'ordered_at', type: 'datetime', schema_valid: false },
            },
        },
    },
    joins: [],
}

const meta: Meta<typeof SelfManagedColumnsSection> = {
    component: SelfManagedColumnsSection,
    title: 'Scenes-App/Data Warehouse/Self-managed columns',
    args: { table: TABLE },
    decorators: [
        mswDecorator({
            post: { '/api/environments/:team_id/query/:kind': DATABASE_SCHEMA },
            get: { '/api/environments/:team_id/warehouse_saved_queries/': { results: [] } },
        }),
    ],
}
export default meta

export const Default: StoryObj<typeof SelfManagedColumnsSection> = {}

export const Narrow: StoryObj<typeof SelfManagedColumnsSection> = {
    decorators: [(Story) => <div className="w-[520px]">{Story()}</div>],
}

export const Viewer: StoryObj<typeof SelfManagedColumnsSection> = {
    args: { table: { ...TABLE, user_access_level: AccessControlLevel.Viewer } },
}
