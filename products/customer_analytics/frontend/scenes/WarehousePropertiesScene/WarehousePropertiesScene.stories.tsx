import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { AvailableFeature } from '~/types'

import type { CustomPropertyDefinitionApi, CustomPropertySyncRunApi } from '../../generated/api.schemas'

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
            external_data_source: '01890000-0000-0000-0000-0000000000e1',
            table_name: 'stripe.customers',
            saved_query_name: null,
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
                job_id: null,
                account_segment: null,
                sync_phase: null,
                attempt: null,
                workflow_id: null,
                workflow_run_id: null,
                temporal_url: null,
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
            external_data_source: '01890000-0000-0000-0000-0000000000e2',
            table_name: 'zendesk.users',
            saved_query_name: null,
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
            external_data_source: '01890000-0000-0000-0000-0000000000e3',
            table_name: 'stripe.subscriptions',
            saved_query_name: null,
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
    {
        id: '01890000-0000-0000-0000-000000000004',
        name: 'Lifecycle stage',
        display_type: 'text',
        target_type: 'person',
        is_canonical: false,
        created_at: '2023-02-13T09:00:00Z',
        created_by: null,
        updated_at: null,
        references: [],
        // View-backed: bound to a materialized view rather than an imported table, so it carries a
        // saved_query and no warehouse source to link through.
        source: {
            id: '01890000-0000-0000-0000-0000000000a4',
            definition: '01890000-0000-0000-0000-000000000004',
            saved_query: '01890000-0000-0000-0000-0000000000d4',
            external_data_source: null,
            table_name: 'enriched_users',
            saved_query_name: 'enriched_users',
            key_column: 'distinct_id',
            column_property_map: { lifecycle: 'lifecycle_stage' },
            is_enabled: true,
            consecutive_failures: 0,
            last_synced_at: '2023-02-15T12:00:00Z',
            last_sync_error: null,
            created_at: '2023-02-13T09:00:00Z',
            created_by: null,
            updated_at: null,
            sync_frequency_interval_seconds: 3600,
            next_sync_at: '2023-02-15T13:00:00Z',
            latest_run: {
                id: '01890000-0000-0000-0000-0000000000b4',
                job_id: null,
                account_segment: null,
                sync_phase: null,
                attempt: null,
                workflow_id: null,
                workflow_run_id: null,
                temporal_url: null,
                trigger: 'scheduled',
                status: 'completed',
                started_at: '2023-02-15T11:59:00Z',
                finished_at: '2023-02-15T12:00:00Z',
                rows_read: 320,
                changed: 12,
                existing: 12,
                produced: 12,
                skipped_missing_person: 0,
                error: null,
                created_at: '2023-02-15T11:59:00Z',
            },
        },
    },
]

const runs: CustomPropertySyncRunApi[] = [
    {
        id: '01890000-0000-0000-0000-0000000000c1',
        job_id: null,
        account_segment: null,
        sync_phase: null,
        attempt: null,
        workflow_id: null,
        workflow_run_id: null,
        temporal_url: null,
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
    {
        id: '01890000-0000-0000-0000-0000000000c2',
        job_id: null,
        account_segment: null,
        sync_phase: null,
        attempt: null,
        workflow_id: null,
        workflow_run_id: null,
        temporal_url: null,
        trigger: 'manual',
        status: 'failed',
        started_at: '2023-02-14T09:00:00Z',
        finished_at: '2023-02-14T09:01:00Z',
        rows_read: 0,
        changed: 0,
        existing: 0,
        produced: 0,
        skipped_missing_person: 0,
        error: 'The warehouse import for this table failed.',
        created_at: '2023-02-14T09:00:00Z',
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
                // The group definition attaches to group type 0, so the tab needs that type to exist.
                '/api/projects/:team_id/groups_types/': () => [
                    200,
                    [
                        {
                            group_type: 'organization',
                            group_type_index: 0,
                            name_singular: 'Organization',
                            name_plural: 'Organizations',
                        },
                    ],
                ],
                // Expanding a row loads its run history, which carries the link to the table's
                // warehouse syncs.
                '/api/projects/:team_id/custom_property_sources/:source_id/runs/': () => [
                    200,
                    { count: runs.length, next: null, previous: null, results: runs },
                ],
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
