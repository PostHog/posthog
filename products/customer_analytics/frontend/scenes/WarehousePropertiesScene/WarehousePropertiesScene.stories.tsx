import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { AvailableFeature } from '~/types'

import type { CustomPropertyDefinitionApi } from '../../generated/api.schemas'

// The Groups tab only renders when group analytics is available, so the story has to grant it.
const userWithGroupAnalytics = {
    ...MOCK_DEFAULT_USER,
    organization: {
        ...MOCK_DEFAULT_ORGANIZATION,
        available_product_features: [{ key: AvailableFeature.GROUP_ANALYTICS, name: 'Group analytics' }],
    },
}

const definitions: CustomPropertyDefinitionApi[] = [
    {
        id: '01890000-0000-0000-0000-000000000001',
        name: 'Billing profile',
        display_type: 'text',
        target_type: 'person',
        is_canonical: false,
        created_at: '2023-02-01T10:00:00Z',
        created_by: null,
        updated_at: null,
        references: [],
        source: {
            id: '01890000-0000-0000-0000-0000000000a1',
            definition: '01890000-0000-0000-0000-000000000001',
            external_data_schema: '01890000-0000-0000-0000-0000000000f1',
            key_column: 'user_email',
            column_property_map: { plan_name: 'billing_plan', mrr_cents: 'billing_mrr' },
            is_enabled: true,
            consecutive_failures: 0,
            last_synced_at: '2023-02-15T14:30:00Z',
            last_sync_error: null,
            created_at: '2023-02-01T10:00:00Z',
            created_by: null,
            updated_at: null,
            sync_frequency_interval_seconds: 86400,
            next_sync_at: '2023-02-16T14:30:00Z',
            latest_run: {
                id: '01890000-0000-0000-0000-0000000000b1',
                trigger: 'scheduled',
                status: 'completed',
                started_at: '2023-02-15T14:29:00Z',
                finished_at: '2023-02-15T14:30:00Z',
                rows_read: 4210,
                changed: 118,
                existing: 112,
                produced: 112,
                skipped_missing_person: 6,
                error: null,
                created_at: '2023-02-15T14:29:00Z',
            },
        },
    },
    {
        id: '01890000-0000-0000-0000-000000000002',
        name: 'Support tier',
        display_type: 'text',
        target_type: 'person',
        is_canonical: false,
        created_at: '2023-02-10T09:00:00Z',
        created_by: null,
        updated_at: null,
        references: [],
        source: {
            id: '01890000-0000-0000-0000-0000000000a2',
            definition: '01890000-0000-0000-0000-000000000002',
            external_data_schema: '01890000-0000-0000-0000-0000000000f2',
            key_column: 'distinct_id',
            column_property_map: { tier: 'support_tier' },
            is_enabled: true,
            consecutive_failures: 1,
            last_synced_at: '2023-02-14T08:00:00Z',
            last_sync_error: 'Column "tier" is missing from the warehouse table.',
            created_at: '2023-02-10T09:00:00Z',
            created_by: null,
            updated_at: null,
            sync_frequency_interval_seconds: 86400,
            next_sync_at: '2023-02-15T08:00:00Z',
            latest_run: null,
        },
    },
    {
        id: '01890000-0000-0000-0000-000000000003',
        name: 'Account revenue',
        display_type: 'currency',
        target_type: 'group',
        group_type_index: 0,
        is_canonical: false,
        created_at: '2023-02-12T09:00:00Z',
        created_by: null,
        updated_at: null,
        references: [],
        source: {
            id: '01890000-0000-0000-0000-0000000000a3',
            definition: '01890000-0000-0000-0000-000000000003',
            external_data_schema: '01890000-0000-0000-0000-0000000000f3',
            key_column: 'account_id',
            column_property_map: { arr_cents: 'account_arr' },
            is_enabled: true,
            consecutive_failures: 0,
            last_synced_at: null,
            last_sync_error: null,
            created_at: '2023-02-12T09:00:00Z',
            created_by: null,
            updated_at: null,
            sync_frequency_interval_seconds: 86400,
            next_sync_at: null,
            latest_run: null,
        },
    },
]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Data Management',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-15',
        pageUrl: urls.warehouseProperties(),
        featureFlags: [FEATURE_FLAGS.WAREHOUSE_PERSON_PROPERTIES],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/custom_property_definitions/': () => [
                    200,
                    { count: definitions.length, next: null, previous: null, results: definitions },
                ],
                '/api/users/@me/': () => [200, userWithGroupAnalytics],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const WarehouseProperties: Story = {}

export const WarehousePropertiesGroupsTab: Story = {
    parameters: { pageUrl: urls.warehouseProperties('groups') },
}
