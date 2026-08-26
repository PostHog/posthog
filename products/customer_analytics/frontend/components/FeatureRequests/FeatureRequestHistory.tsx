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
type EvidenceSnapshot = { id: string; account: RelationSnapshot }
type ShowHistoryTarget = (accountId: string, evidenceId?: string) => void

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

function evidenceSnapshot(value: unknown): EvidenceSnapshot | null {
    if (typeof value !== 'object' || value === null || !('id' in value) || typeof value.id !== 'string') {
        return null
    }
    const account = 'account' in value ? relationSnapshot(value.account) : null
    return account ? { id: value.id, account } : null
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

function historyTargetLabel(
    label: string,
    target: { accountId: string; evidenceId?: string } | null,
    onShowTarget: ShowHistoryTarget
): JSX.Element {
    if (!target) {
        return <span className="font-medium">{label}:</span>
    }
    return (
        <button
            type="button"
            onClick={() => onShowTarget(target.accountId, target.evidenceId)}
            data-attr="feature-request-history-target"
            className="m-0 cursor-pointer border-0 bg-transparent p-0 font-medium text-current hover:text-accent"
        >
            {label}:
        </button>
    )
}

function scalarChange(
    label: string,
    before: string,
    after: string,
    isInitial: boolean,
    onShowTarget: ShowHistoryTarget,
    target: { accountId: string; evidenceId?: string } | null = null
): JSX.Element {
    return (
        <div>
            {historyTargetLabel(label, target, onShowTarget)}{' '}
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

function describeAccountChange(
    change: FeatureRequestHistoryChangeApi,
    isInitial: boolean,
    onShowTarget: ShowHistoryTarget
): JSX.Element {
    const before = relationSnapshot(change.before)
    const after = relationSnapshot(change.after)
    const target = after ?? before
    return scalarChange(
        'Account',
        accountSnapshotName(change.before),
        accountSnapshotName(change.after),
        isInitial,
        onShowTarget,
        target ? { accountId: target.id } : null
    )
}

function describeAccountsChange(
    change: FeatureRequestHistoryChangeApi,
    isInitial: boolean,
    onShowTarget: ShowHistoryTarget
): JSX.Element {
    const before = relationSnapshots(change.before)
    const after = relationSnapshots(change.after)
    const beforeIds = new Set(before.map((account) => account.id))
    const afterIds = new Set(after.map((account) => account.id))
    const added = after.filter((account) => !beforeIds.has(account.id))
    const removed = before.filter((account) => !afterIds.has(account.id))
    const target = added[0] ?? removed[0] ?? after[0] ?? before[0]
    const label = historyTargetLabel('Accounts', target ? { accountId: target.id } : null, onShowTarget)

    if (isInitial) {
        return (
            <div>
                {label} {after.map((account) => account.name).join(', ')}
            </div>
        )
    }
    return (
        <div>
            {label}{' '}
            {[
                added.length ? `added ${added.map((account) => account.name).join(', ')}` : null,
                removed.length ? `removed ${removed.map((account) => account.name).join(', ')}` : null,
            ]
                .filter(Boolean)
                .join('; ')}
        </div>
    )
}

function describeEvidenceChange(change: FeatureRequestHistoryChangeApi, onShowTarget: ShowHistoryTarget): JSX.Element {
    const before = evidenceSnapshot(change.before)
    const after = evidenceSnapshot(change.after)
    const target = after ?? before
    return (
        <div>
            {historyTargetLabel(
                'Evidence',
                target ? { accountId: target.account.id, evidenceId: target.id } : null,
                onShowTarget
            )}{' '}
            {before && after
                ? `updated for ${after.account.name}`
                : after
                  ? `added for ${after.account.name}`
                  : `removed for ${before?.account.name ?? 'an account'}`}
        </div>
    )
}

function describeProductAreasChange(
    change: FeatureRequestHistoryChangeApi,
    isInitial: boolean,
    onShowTarget: ShowHistoryTarget
): JSX.Element {
    const before = relationSnapshots(change.before)
    const after = relationSnapshots(change.after)
    const label = historyTargetLabel('Product areas', null, onShowTarget)

    if (isInitial) {
        return (
            <div>
                {label} {after.map((area) => area.name).join(', ') || 'None'}
            </div>
        )
    }
    const beforeIds = new Set(before.map((area) => area.id))
    const afterIds = new Set(after.map((area) => area.id))
    const added = after.filter((area) => !beforeIds.has(area.id)).map((area) => area.name)
    const removed = before.filter((area) => !afterIds.has(area.id)).map((area) => area.name)
    return (
        <div>
            {label}{' '}
            {[
                added.length ? `added ${added.join(', ')}` : null,
                removed.length ? `removed ${removed.join(', ')}` : null,
            ]
                .filter(Boolean)
                .join('; ')}
        </div>
    )
}

function describeChange(
    change: FeatureRequestHistoryChangeApi,
    isInitial: boolean,
    onShowTarget: ShowHistoryTarget
): JSX.Element | null {
    switch (change.field) {
        case 'status':
            return scalarChange('Status', statusName(change.before), statusName(change.after), isInitial, onShowTarget)
        case 'priority':
            return scalarChange(
                'Priority',
                priorityName(change.before),
                priorityName(change.after),
                isInitial,
                onShowTarget
            )
        case 'account':
            return describeAccountChange(change, isInitial, onShowTarget)
        case 'accounts':
            return describeAccountsChange(change, isInitial, onShowTarget)
        case 'evidence':
            return describeEvidenceChange(change, onShowTarget)
        case 'product_areas':
            return describeProductAreasChange(change, isInitial, onShowTarget)
        default:
            return null
    }
}

export interface FeatureRequestHistoryProps {
    history: readonly FeatureRequestHistoryApi[]
    loading: boolean
    error: string | null
    showingAll: boolean
    onRetry: () => void
    onSetShowingAll: (showingAll: boolean) => void
    onShowTarget: ShowHistoryTarget
}

export function FeatureRequestHistory({
    history,
    loading,
    error,
    showingAll,
    onRetry,
    onSetShowingAll,
    onShowTarget,
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
                                            <div key={change.field}>
                                                {describeChange(change, entry.is_initial, onShowTarget)}
                                            </div>
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
