import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import type { SchemaPartitioningApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { PartitioningSection } from './PartitioningSection'

const HASH_PARTITIONED: SchemaPartitioningApi = {
    mode: 'md5',
    columns: ['id'],
    date_granularity: null,
    change_pending: false,
    available_columns: ['created_at', 'updated_at'],
}

type SectionStoryProps = { schemaId: string; partitioning: SchemaPartitioningApi }
type Story = StoryObj<SectionStoryProps>
const meta: Meta<SectionStoryProps> = {
    title: 'Scenes-App/Data Warehouse/Settings/Table partitioning',
    component: PartitioningSection,
    args: { schemaId: 'schema-1' },
    parameters: { viewMode: 'story' },
    render: ({ schemaId, partitioning }) => {
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/external_data_schemas/:id': () => [200, { id: schemaId, partitioning }],
            },
        })

        return <PartitioningSection schemaId={schemaId} />
    },
}
export default meta

export const HashPartitioned: Story = { args: { partitioning: HASH_PARTITIONED } }
