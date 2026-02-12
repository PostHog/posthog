import { Meta, StoryObj } from '@storybook/react'
import { ComponentProps } from 'react'

import { DatabaseSchemaTable } from '~/queries/schema/schema-general'

import { TablePreview } from './TablePreview'

type Story = StoryObj<typeof TablePreview>

const mockTable: DatabaseSchemaTable = {
    type: 'data_warehouse',
    id: 'dw-events',
    name: 'events',
    format: 'Parquet',
    url_pattern: 's3://posthog/events/*.parquet',
    fields: {
        event: {
            name: 'event',
            hogql_value: 'event',
            type: 'string',
            schema_valid: true,
        },
        timestamp: {
            name: 'timestamp',
            hogql_value: 'timestamp',
            type: 'datetime',
            schema_valid: true,
        },
        distinct_id: {
            name: 'distinct_id',
            hogql_value: 'distinct_id',
            type: 'string',
            schema_valid: true,
        },
        ignored_view: {
            name: 'ignored_view',
            hogql_value: 'ignored_view',
            type: 'view',
            schema_valid: true,
        },
    },
}

type PreviewData = NonNullable<ComponentProps<typeof TablePreview>['previewData']>

const mockPreviewData: PreviewData = [
    {
        event: '$pageview',
        timestamp: '2026-01-15T12:00:00Z',
        distinct_id: 'user_123',
        ignored_view: 'should not render',
    },
    {
        event: '$identify',
        timestamp: '2026-01-15T12:03:15Z',
        distinct_id: 'user_456',
        ignored_view: 'should not render',
    },
    {
        event: '$autocapture',
        timestamp: '2026-01-15T12:09:42Z',
        distinct_id: 'user_789',
        ignored_view: 'should not render',
    },
]

const meta: Meta<typeof TablePreview> = {
    title: 'Components/Table preview',
    component: TablePreview,
    decorators: [
        (Story) => (
            <div className="max-w-4xl">
                <Story />
            </div>
        ),
    ],
    args: {
        table: mockTable,
        emptyMessage: 'Select a table to view preview',
        previewData: mockPreviewData,
        loading: false,
        selectedKey: null,
    },
}

export default meta

export const Default: Story = {}

export const SelectedKey: Story = {
    args: {
        selectedKey: 'event',
    },
}

export const EmptyData: Story = {
    args: {
        previewData: [],
    },
}

export const WithoutTable: Story = {
    args: {
        table: undefined,
    },
}

export const Loading: Story = {
    args: {
        loading: true,
    },
}
