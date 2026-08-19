import type { ComponentType } from 'react'

import { IconArrowCircleRight, IconBuilding, IconDocument, IconFlag, IconFolder, IconPencil } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

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
const FEATURE_REQUEST_HISTORY_PREVIEW_SIZE = 5

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

function accountSnapshotName(value: unknown): string {
    return typeof value === 'object' && value !== null && 'name' in value && typeof value.name === 'string'
        ? value.name
        : 'No account'
}

function evidenceAccountName(value: unknown): string | null {
    if (
        typeof value === 'object' &&
        value !== null &&
        'account' in value &&
        typeof value.account === 'object' &&
        value.account !== null &&
        'name' in value.account &&
        typeof value.account.name === 'string'
    ) {
        return value.account.name
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

function historyMarker(entry: FeatureRequestHistoryApi): ComponentType<{ className?: string }> {
    if (entry.is_initial) {
        return IconDocument
    }
    if (entry.changes.length !== 1) {
        return IconPencil
    }
    switch (entry.changes[0].field) {
        case 'status':
            return IconArrowCircleRight
        case 'priority':
            return IconFlag
        case 'account':
        case 'accounts':
            return IconBuilding
        case 'product_areas':
            return IconFolder
        default:
            return IconPencil
    }
}

function describeChange(change: FeatureRequestHistoryChangeApi, isInitial: boolean): JSX.Element | null {
    if (change.field === 'status') {
        return scalarChange('Status', statusName(change.before), statusName(change.after), isInitial)
    }
    if (change.field === 'priority') {
        return scalarChange('Priority', priorityName(change.before), priorityName(change.after), isInitial)
    }
    if (change.field === 'account') {
        return scalarChange('Account', accountSnapshotName(change.before), accountSnapshotName(change.after), isInitial)
    }
    if (change.field === 'accounts') {
        const before = relationSnapshots(change.before)
        const after = relationSnapshots(change.after)
        if (isInitial) {
            return (
                <div>
                    <span className="font-medium">Accounts:</span> {after.map((account) => account.name).join(', ')}
                </div>
            )
        }
        const beforeIds = new Set(before.map((account) => account.id))
        const afterIds = new Set(after.map((account) => account.id))
        const added = after.filter((account) => !beforeIds.has(account.id)).map((account) => account.name)
        const removed = before.filter((account) => !afterIds.has(account.id)).map((account) => account.name)
        return (
            <div>
                <span className="font-medium">Accounts:</span>{' '}
                {[
                    added.length ? `added ${added.join(', ')}` : null,
                    removed.length ? `removed ${removed.join(', ')}` : null,
                ]
                    .filter(Boolean)
                    .join('; ')}
            </div>
        )
    }
    if (change.field === 'evidence') {
        const beforeAccount = evidenceAccountName(change.before)
        const afterAccount = evidenceAccountName(change.after)
        return (
            <div>
                <span className="font-medium">Evidence:</span>{' '}
                {beforeAccount && afterAccount
                    ? `updated for ${afterAccount}`
                    : afterAccount
                      ? `added for ${afterAccount}`
                      : `removed for ${beforeAccount ?? 'an account'}`}
            </div>
        )
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
    showingAll: boolean
    onRetry: () => void
    onSetShowingAll: (showingAll: boolean) => void
}

export function FeatureRequestHistory({
    history,
    loading,
    error,
    showingAll,
    onRetry,
    onSetShowingAll,
}: FeatureRequestHistoryProps): JSX.Element {
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
    const visibleHistory = showingAll ? history : history.slice(0, FEATURE_REQUEST_HISTORY_PREVIEW_SIZE)

    return (
        <div className="flex flex-col gap-3">
            <div className="relative">
                <span className="absolute bottom-2.5 left-2.5 top-2.5 w-px bg-border" aria-hidden />
                {visibleHistory.map((entry) => {
                    const MarkerIcon = historyMarker(entry)
                    return (
                        <div key={entry.id} className="relative flex gap-3 pb-4 last:pb-0">
                            <span className="z-10 flex size-5 shrink-0 items-center justify-center rounded-full border bg-surface-primary text-secondary">
                                <MarkerIcon className="size-3" />
                            </span>
                            <div className="min-w-0 flex-1">
                                <div className="mb-1 flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5">
                                    <span className="font-medium text-sm text-default">
                                        {entry.actor_name ?? 'Unknown user'}{' '}
                                        {entry.is_initial ? 'created this request' : 'updated this request'}
                                    </span>
                                    <span className="text-xs text-tertiary">
                                        <TZLabel time={entry.changed_at} />
                                    </span>
                                </div>
                                <LemonCard hoverEffect={false} className="w-full p-2 shadow-none">
                                    <div className="flex flex-col gap-1 text-secondary">
                                        {entry.changes.map((change) => (
                                            <div key={change.field}>{describeChange(change, entry.is_initial)}</div>
                                        ))}
                                    </div>
                                </LemonCard>
                            </div>
                        </div>
                    )
                })}
            </div>
            {history.length > FEATURE_REQUEST_HISTORY_PREVIEW_SIZE && (
                <LemonButton
                    type="tertiary"
                    size="small"
                    onClick={() => onSetShowingAll(!showingAll)}
                    data-attr="feature-request-history-show-all"
                    className="ml-8 self-start"
                >
                    {showingAll
                        ? `Show latest ${FEATURE_REQUEST_HISTORY_PREVIEW_SIZE} entries`
                        : `Show all ${history.length} entries`}
                </LemonButton>
            )}
        </div>
    )
}
