import { IconWarning } from '@posthog/icons'
import { LemonTag, Link } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { urls } from 'scenes/urls'

import type { LogsAlertStateChangeSignalExtra } from '~/queries/schema/schema-signals'

import { SignalCardShell } from './SignalCardShell'
import type { SignalCardEntry, SignalCardProps } from './types'

/** Narrows a signal's `extra` to the logs alert state-change shape. */
export function isLogsAlertStateChangeExtra(
    extra: Record<string, unknown>
): extra is Record<string, unknown> & LogsAlertStateChangeSignalExtra {
    return (
        typeof extra.alert_id === 'string' &&
        (extra.action === 'firing' || extra.action === 'broken') &&
        'threshold_count' in extra
    )
}

/** Reads a string array off the loosely-typed filters bag, returning [] when absent or malformed. */
function readStringArray(filters: Record<string, unknown>, key: string): string[] {
    const value = filters[key]
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

/** Compact rendering of the alert's log filters: services, severities, and a count of remaining conditions. */
function FiltersBlock({ filters }: { filters: Record<string, unknown> }): JSX.Element {
    const serviceNames = readStringArray(filters, 'serviceNames')
    const severityLevels = readStringArray(filters, 'severityLevels')
    const filterGroup = filters.filterGroup

    // Best-effort count of extra UniversalFilters conditions without fully expanding them.
    let filterGroupCount = 0
    if (filterGroup && typeof filterGroup === 'object') {
        const values = (filterGroup as { values?: unknown }).values
        if (Array.isArray(values)) {
            filterGroupCount = values.length
        }
    }

    const hasAny = serviceNames.length > 0 || severityLevels.length > 0 || filterGroupCount > 0
    if (!hasAny) {
        return <span className="text-xs text-tertiary">All logs</span>
    }

    return (
        <div className="flex flex-col gap-1">
            {serviceNames.length > 0 && (
                <div className="flex items-center gap-1 flex-wrap">
                    <span className="text-xs text-tertiary">Services</span>
                    {serviceNames.map((name) => (
                        <LemonTag key={name} size="small">
                            {name}
                        </LemonTag>
                    ))}
                </div>
            )}
            {severityLevels.length > 0 && (
                <div className="flex items-center gap-1 flex-wrap">
                    <span className="text-xs text-tertiary">Severities</span>
                    {severityLevels.map((level) => (
                        <LemonTag key={level} size="small">
                            {level}
                        </LemonTag>
                    ))}
                </div>
            )}
            {filterGroupCount > 0 && (
                <LemonTag size="small" type="muted">
                    + {filterGroupCount} filter {filterGroupCount === 1 ? 'condition' : 'conditions'}
                </LemonTag>
            )}
        </div>
    )
}

/** Firing body: threshold sentence plus a compact observed / threshold pair. */
function FiringBody({ extra }: { extra: LogsAlertStateChangeSignalExtra }): JSX.Element {
    const observed = extra.result_count === null ? 'No result' : extra.result_count

    return (
        <div className="flex flex-col gap-2">
            <p className="text-sm m-0">
                Result count {observed} is {extra.threshold_operator} threshold {extra.threshold_count} over the last{' '}
                {extra.window_minutes} minutes
            </p>
            <div className="flex items-baseline gap-2">
                <span className="text-lg font-semibold">
                    <span className="text-danger">{extra.result_count === null ? '–' : extra.result_count}</span>
                    {' / '}
                    {extra.threshold_count}
                </span>
                <span className="text-xs text-tertiary">observed / threshold</span>
            </div>
        </div>
    )
}

/** Broken body: auto-disable sentence plus a muted line describing what was being checked. */
function BrokenBody({ extra }: { extra: LogsAlertStateChangeSignalExtra }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <p className="text-sm m-0">
                Alert auto-disabled after{' '}
                <span className="text-warning font-semibold">{extra.consecutive_failures}</span> consecutive failed
                checks
            </p>
            <p className="text-xs text-tertiary m-0">
                Was checking result count {extra.threshold_operator} {extra.threshold_count} over {extra.window_minutes}
                m
            </p>
        </div>
    )
}

/** Inbox signal card for logs alert state changes (firing / broken). */
export function LogsAlertSignalCard({ signal }: SignalCardProps): JSX.Element {
    if (!isLogsAlertStateChangeExtra(signal.extra)) {
        return <SignalCardShell signal={signal}>{null}</SignalCardShell>
    }
    const extra = signal.extra
    const alertUrl = urls.logsAlertDetail(extra.alert_id)

    const stateBadge =
        extra.action === 'firing' ? (
            <LemonTag type="danger" size="small">
                Firing
            </LemonTag>
        ) : (
            <LemonTag type="warning" size="small" icon={<IconWarning />}>
                Broken
            </LemonTag>
        )

    return (
        <SignalCardShell signal={signal} label={extra.alert_name} rightSlot={stateBadge}>
            <div className="flex flex-col gap-3">
                {extra.action === 'firing' ? <FiringBody extra={extra} /> : <BrokenBody extra={extra} />}

                {signal.content && (
                    <LemonMarkdown className="text-sm text-secondary" disableImages>
                        {signal.content}
                    </LemonMarkdown>
                )}

                <FiltersBlock filters={extra.filters} />

                <div className="flex items-center gap-2 text-xs">
                    <span className="flex-1" />
                    <Link to={alertUrl} className="font-medium shrink-0">
                        View alert
                    </Link>
                </div>
            </div>
        </SignalCardShell>
    )
}

export const logsAlertSignalCardEntry: SignalCardEntry = {
    key: 'logs',
    matches: (signal) => signal.source_product === 'logs' && isLogsAlertStateChangeExtra(signal.extra),
    Component: LogsAlertSignalCard,
}
