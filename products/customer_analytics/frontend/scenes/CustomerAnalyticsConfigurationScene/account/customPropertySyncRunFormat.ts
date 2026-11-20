import { humanFriendlyDuration } from 'lib/utils/durations'
import { percentage } from 'lib/utils/numbers'

import type { CustomPropertySyncRunApi } from 'products/customer_analytics/frontend/generated/api.schemas'

export const RUN_STATUS_LABELS: Record<string, string> = {
    completed: 'Completed',
    running: 'Running',
    failed: 'Failed',
}

export const ACCOUNT_SEGMENT_LABELS: Record<string, string> = {
    tracked: 'Tracked',
    ignored: 'Ignored',
}

export type TargetType = 'account' | 'person' | 'group'

type TargetLabels = {
    entity: string
    entityPlural: string
}

export const TARGET_LABELS: Record<TargetType, TargetLabels> = {
    account: { entity: 'account', entityPlural: 'accounts' },
    person: { entity: 'person', entityPlural: 'people' },
    group: { entity: 'group', entityPlural: 'groups' },
}

export function runDuration(run: CustomPropertySyncRunApi): string {
    if (!run.started_at || !run.finished_at) {
        return '-'
    }
    const seconds = Math.max((new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000, 0)
    return humanFriendlyDuration(seconds, { maxUnits: 2 })
}

export function updatedShare(existing: number, changed: number): string | null {
    if (changed <= 0) {
        return null
    }
    if (existing >= changed) {
        return '100%'
    }
    const share = existing / changed
    if (share < 0.01) {
        return '<1%'
    }
    return percentage(Math.min(share, 0.99), 0)
}
