import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type {
    FeatureRequestHistoryApi,
    FeatureRequestHistoryChangeApi,
    FeatureRequestStatusEnumApi,
    RequestPriorityEnumApi,
} from '../../generated/api.schemas'
import { featureRequestPriorityLabel, featureRequestStatusLabel } from './featureRequestOptions'

type RelationSnapshot = { id: string; name: string }

const FEATURE_REQUEST_STATUSES = new Set<string>(['requested', 'planned', 'completed', 'wont_fix', 'duplicate'])
const FEATURE_REQUEST_PRIORITIES = new Set<string>(['high', 'medium', 'low'])

function relationSnapshot(value: unknown): RelationSnapshot | null {
    if (
        typeof value === 'object' &&
        value !== null &&
        'id' in value &&
        typeof value.id === 'string' &&
        'name' in value &&
        typeof value.name === 'string'
    ) {
        return { id: value.id, name: value.name }
    }
    return null
}

function relationSnapshots(value: unknown): RelationSnapshot[] {
    return Array.isArray(value)
        ? value.map(relationSnapshot).filter((snapshot): snapshot is RelationSnapshot => snapshot !== null)
        : []
}

function statusName(value: unknown): string {
    return typeof value === 'string' && FEATURE_REQUEST_STATUSES.has(value)
        ? featureRequestStatusLabel(value as FeatureRequestStatusEnumApi)
        : 'Unknown status'
}

function priorityName(value: unknown): string {
    return value === null || (typeof value === 'string' && FEATURE_REQUEST_PRIORITIES.has(value))
        ? featureRequestPriorityLabel(value as RequestPriorityEnumApi | null)
        : 'Unknown priority'
}

function scalarChange(label: string, before: string, after: string, isInitial: boolean): JSX.Element {
    return (
        <div>
            <span className="font-medium">{label}:</span>{' '}
            {isInitial ? (
                after
            ) : (
                <>
                    <span className="text-secondary">{before}</span>
                    <span className="mx-1 text-tertiary" aria-label="changed to">
                        →
                    </span>
                    {after}
                </>
            )}
        </div>
    )
}

function describeChange(change: FeatureRequestHistoryChangeApi, isInitial: boolean): JSX.Element | null {
    if (change.field === 'status') {
        return scalarChange('Status', statusName(change.before), statusName(change.after), isInitial)
    }
    if (change.field === 'priority') {
        return scalarChange('Priority', priorityName(change.before), priorityName(change.after), isInitial)
    }
    if (change.field === 'account') {
        const before = relationSnapshot(change.before)?.name ?? 'No account'
        const after = relationSnapshot(change.after)?.name ?? 'No account'
        return scalarChange('Account', before, after, isInitial)
    }
    if (change.field === 'product_areas') {
        const before = relationSnapshots(change.before)
        const after = relationSnapshots(change.after)
        if (isInitial) {
            return (
                <div>
                    <span className="font-medium">Product areas:</span>{' '}
                    {after.map((area) => area.name).join(', ') || 'None'}
                </div>
            )
        }
        const beforeIds = new Set(before.map((area) => area.id))
        const afterIds = new Set(after.map((area) => area.id))
        const added = after.filter((area) => !beforeIds.has(area.id)).map((area) => area.name)
        const removed = before.filter((area) => !afterIds.has(area.id)).map((area) => area.name)
        return (
            <div>
                <span className="font-medium">Product areas:</span>{' '}
                {[
                    added.length ? `added ${added.join(', ')}` : null,
                    removed.length ? `removed ${removed.join(', ')}` : null,
                ]
                    .filter(Boolean)
                    .join('; ')}
            </div>
        )
    }
    return null
}

export interface FeatureRequestHistoryProps {
    history: readonly FeatureRequestHistoryApi[]
    loading: boolean
    error: string | null
    onRetry: () => void
}

export function FeatureRequestHistory({ history, loading, error, onRetry }: FeatureRequestHistoryProps): JSX.Element {
    if (loading) {
        return (
            <div className="flex flex-col gap-2">
                <LemonSkeleton className="h-16 w-full rounded" />
                <LemonSkeleton className="h-16 w-full rounded" />
            </div>
        )
    }
    if (error) {
        return (
            <LemonBanner type="error">
                <div className="flex flex-col items-start gap-2">
                    <span>{error}</span>
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        onClick={onRetry}
                        data-attr="feature-request-history-retry"
                    >
                        Try again
                    </LemonButton>
                </div>
            </LemonBanner>
        )
    }
    if (history.length === 0) {
        return <div className="text-secondary">No history yet.</div>
    }
    return (
        <div className="flex flex-col divide-y divide-border">
            {history.map((entry) => (
                <div key={entry.id} className="flex flex-col gap-1.5 py-3 first:pt-0 last:pb-0">
                    <div className="font-medium">
                        {entry.actor_name ?? 'Unknown user'}{' '}
                        {entry.is_initial ? 'created this request' : 'updated this request'}
                    </div>
                    <div className="flex flex-col gap-1 text-secondary">
                        {entry.changes.map((change, index) => (
                            <div key={`${change.field}-${index}`}>{describeChange(change, entry.is_initial)}</div>
                        ))}
                    </div>
                    <div className="text-xs text-tertiary">
                        <TZLabel time={entry.changed_at} />
                    </div>
                </div>
            ))}
        </div>
    )
}
