import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { CustomPropertyDisplayTypeEnumApi } from 'products/customer_analytics/frontend/generated/api.schemas'
import type {
    CustomPropertyDefinitionApi,
    CustomPropertySourceApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { WarehousePersonPropertiesSetting } from './WarehousePersonPropertiesSetting'

jest.mock('kea', () => ({ ...jest.requireActual('kea'), useActions: jest.fn(), useValues: jest.fn() }))
jest.mock('lib/components/RestrictedArea', () => ({
    RestrictionScope: { Project: 'project' },
    useRestrictedArea: jest.fn(),
}))
jest.mock('./CustomPropertyModal', () => ({ CustomPropertyModal: () => null }))

describe('WarehousePersonPropertiesSetting', () => {
    const EDIT_ACTIONS = [
        'add-warehouse-profile-property',
        'sync-warehouse-profile-property',
        'backfill-warehouse-profile-property',
        'edit-warehouse-profile-property',
    ]
    const DELETE_ACTION = 'delete-warehouse-profile-property'

    // A source the sync and backfill buttons can act on — without one they're disabled whatever
    // the caller's access level is, and the permission assertions would pass vacuously.
    const source: CustomPropertySourceApi = {
        id: 'source-1',
        definition: 'definition-1',
        saved_query: null,
        external_data_schema: 'schema-1',
        column_property_map: { plan: 'plan_tier' },
        key_column: 'distinct_id',
        is_enabled: true,
        consecutive_failures: 0,
        last_synced_at: '2026-01-01T00:00:00Z',
        last_sync_error: null,
        created_at: '2026-01-01T00:00:00Z',
        created_by: 1,
        updated_at: null,
        sync_frequency_interval_seconds: 3600,
        next_sync_at: '2026-01-01T01:00:00Z',
        latest_run: null,
        external_data_source: 'warehouse-source-1',
        table_name: 'stripe_customers',
        saved_query_name: null,
    }
    const propertyDefinition: CustomPropertyDefinitionApi = {
        id: 'definition-1',
        name: 'Plan tier',
        description: null,
        display_type: CustomPropertyDisplayTypeEnumApi.Text,
        is_big_number: false,
        target_type: 'person',
        group_type_index: null,
        is_canonical: false,
        options: null,
        source,
        created_at: '2026-01-01T00:00:00Z',
        created_by: 1,
        updated_at: null,
        references: [],
        has_workflow_reference: false,
    }

    let previousAppContext: AppContext | undefined

    const isDisabled = (dataAttr: string): boolean =>
        document.querySelector(`[data-attr="${dataAttr}"]`)!.getAttribute('aria-disabled') === 'true'

    beforeEach(() => {
        previousAppContext = window.POSTHOG_APP_CONTEXT
        ;(useValues as jest.Mock).mockReturnValue({
            definitions: [propertyDefinition],
            definitionsInitialLoading: false,
            triggeringSourceIds: [],
            runsBySourceId: {},
            runsCountBySourceId: {},
            runsOffsetBySourceId: {},
            runsSearchBySourceId: {},
            runsLoadingBySourceId: {},
            runsLoadFailedBySourceId: {},
        })
        ;(useActions as jest.Mock).mockReturnValue({
            openCreateModal: jest.fn(),
            openEditModal: jest.fn(),
            deleteDefinition: jest.fn(),
            triggerSync: jest.fn(),
            triggerBackfill: jest.fn(),
            setRunsSearch: jest.fn(),
            loadRuns: jest.fn(),
        })
    })

    afterEach(() => {
        cleanup()
        window.POSTHOG_APP_CONTEXT = previousAppContext
    })

    test.each([
        {
            caller: 'project member with Customer analytics editor access',
            membershipLevel: TeamMembershipLevel.Member,
            resourceLevel: AccessControlLevel.Editor,
            disabledActions: [DELETE_ACTION],
        },
        {
            // Runs as an admin on purpose: the admin gate would otherwise mask a missing editor
            // check on delete.
            caller: 'project admin without Customer analytics editor access',
            membershipLevel: TeamMembershipLevel.Admin,
            resourceLevel: AccessControlLevel.Viewer,
            disabledActions: [...EDIT_ACTIONS, DELETE_ACTION],
        },
    ])('gates the warehouse property actions for a $caller', ({ membershipLevel, resourceLevel, disabledActions }) => {
        ;(useRestrictedArea as jest.Mock).mockImplementation(
            ({ minimumAccessLevel }: { minimumAccessLevel: TeamMembershipLevel }) =>
                minimumAccessLevel > membershipLevel ? 'Project admin access is required' : null
        )
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: { [AccessControlResourceType.CustomerAnalytics]: resourceLevel },
        } as unknown as AppContext

        render(<WarehousePersonPropertiesSetting />)

        expect([...EDIT_ACTIONS, DELETE_ACTION].filter(isDisabled)).toEqual(disabledActions)
    })
})
