import clsx from 'clsx'

import { LemonTag } from '@posthog/lemon-ui'

import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import type { LinearIssueSignalExtraApi } from 'products/signals/frontend/generated/api.schemas'

import { ExternalSignalCard, type StatePill } from './ExternalSignalCard'
import type { SignalCardEntry, SignalCardProps } from './types'

/**
 * Linear has `url` + `priority` + `number`, but unlike GitHub it carries no `html_url`.
 * Requiring `identifier` and `priority_label` keeps this narrow enough not to match other issue sources.
 */
export function isLinearIssueExtra(value: unknown): value is Record<string, unknown> & LinearIssueSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return 'identifier' in extra && 'priority_label' in extra && typeof extra.url === 'string'
}

/** Linear workflow state types → state pill tone. */
function statePillForState(extra: LinearIssueSignalExtraApi): StatePill | undefined {
    if (!extra.state_name) {
        return undefined
    }
    const tone: StatePill['tone'] =
        extra.state_type === 'started'
            ? 'warning'
            : extra.state_type === 'completed'
              ? 'success'
              : extra.state_type === 'canceled' || extra.state_type === 'backlog'
                ? 'muted'
                : 'default'
    return { label: extra.state_name, tone }
}

/** Tailwind text colour for a Linear priority dot. `0` (No priority) stays muted. */
const PRIORITY_DOT_CLASS: Record<number, string> = {
    1: 'text-danger',
    2: 'text-warning',
    3: 'text-primary',
    4: 'text-muted',
}

function PriorityIndicator({ extra }: { extra: LinearIssueSignalExtraApi }): JSX.Element {
    const dotClass = PRIORITY_DOT_CLASS[extra.priority] ?? 'text-muted'
    const label = extra.priority === 0 ? extra.priority_label || 'No priority' : extra.priority_label
    return (
        <span className={clsx('inline-flex items-center gap-1 text-xs', extra.priority === 0 && 'text-muted')}>
            <span className={clsx('size-1.5 rounded-full bg-current', dotClass)} />
            {label}
        </span>
    )
}

export function LinearIssueSignalCard({ signal }: SignalCardProps): JSX.Element {
    const extra = signal.extra as Record<string, unknown> & LinearIssueSignalExtraApi

    const title = extra.identifier || `#${extra.number}`
    const labels = Array.isArray(extra.labels) ? extra.labels : []

    const metaChips = (
        <>
            <PriorityIndicator extra={extra} />
            {extra.team_name && (
                <LemonTag size="small" type="muted">
                    {extra.team_name}
                </LemonTag>
            )}
            {labels.map((label) => (
                <LemonTag key={label} size="small">
                    {label}
                </LemonTag>
            ))}
        </>
    )

    const footerLeft = (
        <span>
            Opened {humanFriendlyDetailedTime(extra.created_at)}
            {extra.updated_at !== extra.created_at && <> · Updated {humanFriendlyDetailedTime(extra.updated_at)}</>}
        </span>
    )

    return (
        <ExternalSignalCard
            signal={signal}
            title={<span className="font-mono">{title}</span>}
            statePill={statePillForState(extra)}
            metaChips={metaChips}
            footerLeft={footerLeft}
            link={{ to: extra.url, label: 'View in Linear' }}
        >
            {signal.content}
        </ExternalSignalCard>
    )
}

export const linearIssueSignalCardEntry: SignalCardEntry = {
    key: 'linear',
    matches: (signal) => signal.source_product === 'linear' && isLinearIssueExtra(signal.extra),
    Component: LinearIssueSignalCard,
}
