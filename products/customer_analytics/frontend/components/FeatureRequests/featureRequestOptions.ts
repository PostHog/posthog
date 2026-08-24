import type { LemonTagType } from '@posthog/lemon-ui'

import type { FeatureRequestStatusEnumApi, RequestPriorityEnumApi } from '../../generated/api.schemas'

export type FeatureRequestArchiveState = 'active' | 'archived' | 'all'
export type FeatureRequestOrdering =
    | '-updated_at'
    | 'updated_at'
    | '-created_at'
    | 'created_at'
    | '-priority'
    | 'priority'
    | 'title'
    | '-title'
export type FeatureRequestPriorityFilter = RequestPriorityEnumApi | 'none'

export const FEATURE_REQUEST_STATUS_OPTIONS: { value: FeatureRequestStatusEnumApi; label: string }[] = [
    { value: 'requested', label: 'Requested' },
    { value: 'planned', label: 'Planned' },
    { value: 'completed', label: 'Completed' },
    { value: 'wont_fix', label: "Won't fix" },
    { value: 'duplicate', label: 'Duplicate' },
]

export const FEATURE_REQUEST_PRIORITY_OPTIONS: { value: RequestPriorityEnumApi; label: string }[] = [
    { value: 'high', label: 'High' },
    { value: 'medium', label: 'Medium' },
    { value: 'low', label: 'Low' },
]

export const FEATURE_REQUEST_PRIORITY_FILTER_OPTIONS: { value: FeatureRequestPriorityFilter; label: string }[] = [
    ...FEATURE_REQUEST_PRIORITY_OPTIONS,
    { value: 'none', label: 'No priority' },
]

export const FEATURE_REQUEST_ARCHIVE_OPTIONS: { value: FeatureRequestArchiveState; label: string }[] = [
    { value: 'active', label: 'Active' },
    { value: 'archived', label: 'Archived' },
    { value: 'all', label: 'All requests' },
]

export const FEATURE_REQUEST_ORDERING_OPTIONS: { value: FeatureRequestOrdering; label: string }[] = [
    { value: '-updated_at', label: 'Recently updated' },
    { value: 'updated_at', label: 'Least recently updated' },
    { value: '-created_at', label: 'Newest created' },
    { value: 'created_at', label: 'Oldest created' },
    { value: '-priority', label: 'Highest priority' },
    { value: 'priority', label: 'Lowest priority' },
    { value: 'title', label: 'Title A to Z' },
    { value: '-title', label: 'Title Z to A' },
]

export function featureRequestStatusLabel(status: FeatureRequestStatusEnumApi): string {
    return FEATURE_REQUEST_STATUS_OPTIONS.find((option) => option.value === status)?.label ?? status
}

export function featureRequestStatusTagType(status: FeatureRequestStatusEnumApi): LemonTagType {
    switch (status) {
        case 'planned':
            return 'warning'
        case 'completed':
            return 'success'
        case 'wont_fix':
            return 'muted'
        case 'duplicate':
            return 'default'
        default:
            return 'primary'
    }
}

export function featureRequestPriorityLabel(priority: RequestPriorityEnumApi | null): string {
    return priority
        ? (FEATURE_REQUEST_PRIORITY_OPTIONS.find((option) => option.value === priority)?.label ?? priority)
        : 'No priority'
}
