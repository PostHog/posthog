import { Meta, StoryFn } from '@storybook/react'

import { ExternalDataDestinationApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { DestinationList, DestinationListProps } from './DestinationList'

const WAREHOUSE: ExternalDataDestinationApi = {
    id: '01a03e9c-1b76-0000-9079-2a0ee2186dea',
    type: 'PostHogWarehouse',
    name: 'PostHog warehouse',
    config: {},
    integration: null,
    is_posthog_warehouse: true,
    created_at: '2026-08-20T10:00:00Z',
    updated_at: '2026-08-25T10:00:00Z',
    created_by: null,
} as ExternalDataDestinationApi

const POSTGRES: ExternalDataDestinationApi = {
    id: '01a03e9c-1b7c-0000-71ce-5e5d7b04df8f',
    type: 'Postgres',
    name: 'Customer Postgres',
    config: { database: 'analytics', schema: 'customer_sync' },
    integration: 1,
    is_posthog_warehouse: false,
    created_at: '2026-08-24T10:00:00Z',
    updated_at: '2026-08-26T14:00:00Z',
    created_by: null,
} as ExternalDataDestinationApi

const meta: Meta<typeof DestinationList> = {
    title: 'Data Warehouse/DestinationList',
    component: DestinationList,
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof DestinationList> = (props: DestinationListProps) => <DestinationList {...props} />

export const BothSelected = Template.bind({})
BothSelected.args = {
    destinations: [POSTGRES, WAREHOUSE],
    loading: false,
    selectedIds: [POSTGRES.id, WAREHOUSE.id],
    onToggle: () => {},
    onEdit: () => {},
}

// The last one on cannot be turned off, so a source can never end up syncing nowhere.
export const OnlyOneLeft = Template.bind({})
OnlyOneLeft.args = {
    ...BothSelected.args,
    selectedIds: [WAREHOUSE.id],
}

export const InheritedFromSource = Template.bind({})
InheritedFromSource.args = {
    ...BothSelected.args,
    toggleDisabledReason: 'This table follows its source. Turn on the override to change it.',
}

export const Loading = Template.bind({})
Loading.args = {
    ...BothSelected.args,
    destinations: [],
    loading: true,
}
Loading.parameters = {
    // This story shows a permanent loading state by design, so the test runner must not
    // wait for the loader to disappear before taking its snapshot.
    testOptions: { waitForLoadersToDisappear: false },
}

export const Empty = Template.bind({})
Empty.args = {
    ...BothSelected.args,
    destinations: [],
    selectedIds: [],
}
