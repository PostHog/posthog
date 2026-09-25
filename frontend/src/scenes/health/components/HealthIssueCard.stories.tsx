import type { Meta, StoryFn } from '@storybook/react'

import type { HealthIssue } from '../types'
import { HealthIssueCard } from './HealthIssueCard'

const SDK_OUTDATED_ISSUE: HealthIssue = {
    id: 'sdk-1',
    kind: 'sdk_outdated',
    severity: 'critical',
    status: 'active',
    dismissed: false,
    snoozed_until: null,
    created_at: '2024-12-02T08:00:00Z',
    updated_at: '2025-01-14T20:00:00Z',
    resolved_at: null,
    payload: {
        sdk_name: 'web',
        latest_version: '1.142.0',
        current_version: '1.130.0',
        is_outdated: true,
        is_old: true,
        reason: 'Latest in-use version 1.130.0 is behind latest 1.142.0.',
        banners: [],
        usage: [
            {
                lib_version: '1.130.0',
                count: 51204,
                max_timestamp: '2025-01-14T22:15:00Z',
                release_date: '2024-10-02T00:00:00Z',
                is_latest: false,
                is_outdated: true,
                status_reason: 'Released 3 months ago. Upgrade to pick up bug fixes.',
            },
        ],
    },
}

// No check run since detection, so "Last checked" matches the detection time.
const STALE_ISSUE: HealthIssue = {
    ...SDK_OUTDATED_ISSUE,
    id: 'sdk-2',
    updated_at: SDK_OUTDATED_ISSUE.created_at,
}

const noop = (): void => {}

const meta: Meta = {
    title: 'Scenes-App/Health/Issue card',
    parameters: {
        mockDate: '2025-01-15',
        viewMode: 'story',
    },
}
export default meta

export const RecentlyChecked: StoryFn = () => (
    <HealthIssueCard issue={SDK_OUTDATED_ISSUE} onSnooze={noop} onDismiss={noop} onUndismiss={noop} />
)

export const NotCheckedSinceDetection: StoryFn = () => (
    <HealthIssueCard issue={STALE_ISSUE} onSnooze={noop} onDismiss={noop} onUndismiss={noop} />
)
