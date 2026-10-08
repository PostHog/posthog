import { PropValue } from '~/models/propertyDefinitionsModel'
import { HogFunctionConfigurationContextId } from '~/types'

import { ActivityLogListScope } from 'products/platform_features/frontend/generated/api.schemas'

export type FilterOption = { value: string; label: string }

// NOTE: This is all a bit WIP and will be improved upon over time
// TODO: Make this more advanced with sub type filtering etc.
// TODO: Make it possible for the renderer to limit the options based on the type
/**
 * Options for the 'Trigger' field on the new destination page
 */
export const getProductEventFilterOptions = (contextId: HogFunctionConfigurationContextId): FilterOption[] => {
    switch (contextId) {
        case 'error-tracking':
            return [
                {
                    label: 'Error tracking issue created',
                    value: '$error_tracking_issue_created',
                },
                {
                    label: 'Error tracking issue reopened',
                    value: '$error_tracking_issue_reopened',
                },
                {
                    label: 'Error tracking issue spiking',
                    value: '$error_tracking_issue_spiking',
                },
                {
                    label: 'Error tracking issue resolved',
                    value: '$error_tracking_issue_resolved',
                },
                {
                    label: 'Error tracking issue suppressed',
                    value: '$error_tracking_issue_suppressed',
                },
                {
                    label: 'Error tracking issue assigned',
                    value: '$error_tracking_issue_assigned',
                },
                {
                    label: 'Error tracking issue unassigned',
                    value: '$error_tracking_issue_unassigned',
                },
                {
                    label: 'Error tracking issue merged',
                    value: '$error_tracking_issue_merged',
                },
                {
                    label: 'Error tracking issue split',
                    value: '$error_tracking_issue_split',
                },
            ]
        case 'insight-alerts':
            return [
                {
                    label: 'Insight alert firing',
                    value: '$insight_alert_firing',
                },
            ]
        case 'logs-alerting':
            return [
                {
                    label: 'Log alert firing',
                    value: '$logs_alert_firing',
                },
                {
                    label: 'Log alert resolved',
                    value: '$logs_alert_resolved',
                },
                {
                    label: 'Log alert auto-disabled',
                    value: '$logs_alert_auto_disabled',
                },
                {
                    label: 'Log alert errored',
                    value: '$logs_alert_errored',
                },
            ]
        case 'discussion-mention':
            return [
                {
                    label: 'Discussion mention',
                    value: '$discussion_mention_created',
                },
            ]
        case 'health-alerts':
            return [
                {
                    label: 'Health check fired',
                    value: '$health_check_issue_firing',
                },
                {
                    label: 'Health check resolved',
                    value: '$health_check_issue_resolved',
                },
            ]
        case 'batch-export-alerts':
            return [
                {
                    label: 'Batch export run failed',
                    value: '$batch_export_run_failed',
                },
            ]
        default:
            return [
                {
                    label: 'Team activity',
                    value: '$activity_log_entry_created',
                },
                {
                    label: 'Early access feature updated',
                    value: '$early_access_feature_updated',
                },
            ]
    }
}

export const getProductEventPropertyFilterOptions = (contextId: HogFunctionConfigurationContextId): string[] => {
    switch (contextId) {
        case 'activity-log':
            return [
                'id',
                'unread',
                'organization_id',
                'was_impersonated',
                'is_system',
                'activity',
                'item_id',
                'scope',
                'detail',
                'detail.name',
                'detail.changes',
                'created_at',
            ]
        case 'error-tracking':
            return [
                '$exception_types',
                '$exception_values',
                '$exception_sources',
                '$exception_functions',
                '$exception_handled',
            ]
    }

    return []
}

// Hoisted so repeated calls return stable references, keeping downstream memos idle.
// The generated enum mirrors the backend ActivityScope literal, unlike the handwritten
// frontend ActivityScope enum, which lags behind it.
const ACTIVITY_LOG_SCOPE_VALUES: PropValue[] = Object.values(ActivityLogListScope)
    .sort()
    .map((name) => ({ name }))
// The standard lifecycle activities. Scopes also log custom activities (e.g. 'exported'),
// which can still be entered as custom values.
const ACTIVITY_LOG_ACTIVITY_VALUES: PropValue[] = ['created', 'updated', 'deleted'].map((name) => ({ name }))
const NO_SUGGESTED_VALUES: PropValue[] = []

/**
 * Value suggestions for the property filters on the 'Trigger' field. Internal events are
 * never ingested into ClickHouse, so the default events-table suggestions would surface
 * values of same-named properties from unrelated analytics events. Instead, offer the
 * statically known values, and no suggestions (free text) for keys without a known value set.
 */
export const getProductEventPropertyValues = (
    contextId: HogFunctionConfigurationContextId,
    propertyKey: string
): PropValue[] | null => {
    if (contextId !== 'activity-log') {
        return null
    }
    switch (propertyKey) {
        case 'scope':
            return ACTIVITY_LOG_SCOPE_VALUES
        case 'activity':
            return ACTIVITY_LOG_ACTIVITY_VALUES
        default:
            return NO_SUGGESTED_VALUES
    }
}
