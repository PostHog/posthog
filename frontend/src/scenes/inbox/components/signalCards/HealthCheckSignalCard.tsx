import { Fragment } from 'react'

import { LemonTag, Link } from '@posthog/lemon-ui'
import type { LemonTagType } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import type {
    HealthCheckSignalExtraSeverityEnumApi,
    HealthCheckSignalExtraApi,
} from 'products/signals/frontend/generated/api.schemas'

import { SignalCardShell } from './SignalCardShell'
import type { SignalCardEntry, SignalCardProps } from './types'

/**
 * Health-check signals are PostHog-native instrumentation issues. They always carry a `kind`,
 * a `severity`, and an `issue_id`, which together distinguish them from other native sources.
 */
export function isHealthCheckExtra(value: unknown): value is Record<string, unknown> & HealthCheckSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return 'kind' in extra && 'severity' in extra && 'issue_id' in extra
}

/** Severity → LemonTag tone for the header right slot. */
const SEVERITY_TAG_TYPE: Record<HealthCheckSignalExtraSeverityEnumApi, LemonTagType> = {
    critical: 'danger',
    warning: 'warning',
    info: 'muted',
}

/** Human labels for known health-check kinds. Unknown kinds fall back to a humanized form. */
const KIND_LABELS: Record<string, string> = {
    authorized_urls: 'Authorized URLs not set',
    no_live_events: 'No live events',
    no_pageleave_events: 'Missing pageleave events',
    partial_proxy: 'Partial reverse-proxy coverage',
    reverse_proxy: 'Reverse proxy recommended',
    scroll_depth: 'Missing scroll-depth data',
    web_vitals: 'Missing web vitals',
    sdk_outdated: 'Outdated SDK',
    materialized_view_failure: 'Materialized view failing',
    ingestion_warning: 'Ingestion warning',
}

function capitalize(value: string): string {
    return value.length > 0 ? value.charAt(0).toUpperCase() + value.slice(1) : value
}

function kindLabel(kind: string): string {
    return KIND_LABELS[kind] ?? capitalize(kind.replace(/_/g, ' '))
}

/** Turn a snake_case payload key into a readable label, e.g. `current_version` → `Current version`. */
function humanizeKey(key: string): string {
    return capitalize(key.replace(/_/g, ' '))
}

function isPrimitive(value: unknown): value is string | number | boolean {
    return typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
}

/** Format a single primitive value for display (booleans become Yes/No). */
function formatPrimitive(value: string | number | boolean): string {
    if (typeof value === 'boolean') {
        return value ? 'Yes' : 'No'
    }
    return String(value)
}

/**
 * Format a payload value into a display string, or return null to omit it.
 * Nested objects and arrays of objects are omitted to avoid rendering "[object Object]".
 */
function formatPayloadValue(value: unknown): string | null {
    if (isPrimitive(value)) {
        return formatPrimitive(value)
    }
    if (Array.isArray(value)) {
        const primitives = value.filter(isPrimitive)
        if (primitives.length !== value.length || primitives.length === 0) {
            return null
        }
        const formatted = primitives.map(formatPrimitive)
        if (formatted.length > 5) {
            return `${formatted.slice(0, 5).join(', ')} +${formatted.length - 5} more`
        }
        return formatted.join(', ')
    }
    return null
}

/** Generic readable key-value list over an `extra.payload`. Skips `reason` (shown as the summary). */
function PayloadKeyValueList({ payload }: { payload: Record<string, unknown> }): JSX.Element | null {
    const rows = Object.entries(payload)
        .filter(([key]) => key !== 'reason')
        .map(([key, value]) => [key, formatPayloadValue(value)] as const)
        .filter((row): row is readonly [string, string] => row[1] !== null)

    if (rows.length === 0) {
        return null
    }

    return (
        <div className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-xs">
            {rows.map(([key, value]) => (
                <Fragment key={key}>
                    <span className="text-tertiary">{humanizeKey(key)}</span>
                    <span className="text-secondary">{value}</span>
                </Fragment>
            ))}
        </div>
    )
}

/** `sdk_outdated`: render the version upgrade as a single `current → latest` line. */
function SdkOutdatedPayload({ payload }: { payload: Record<string, unknown> }): JSX.Element | null {
    const current = payload.current_version
    const latest = payload.latest_version
    if (!isPrimitive(current) || !isPrimitive(latest)) {
        return <PayloadKeyValueList payload={payload} />
    }
    return (
        <div className="text-xs text-secondary">
            <span className="font-mono">{formatPrimitive(current)}</span>
            <span className="text-tertiary"> → </span>
            <span className="font-mono">{formatPrimitive(latest)}</span>
        </div>
    )
}

/** `partial_proxy`: render unproxied hosts as monospace host chips. */
function PartialProxyPayload({ payload }: { payload: Record<string, unknown> }): JSX.Element | null {
    const hosts = Array.isArray(payload.unproxied_hosts) ? payload.unproxied_hosts.filter(isPrimitive) : []
    if (hosts.length === 0) {
        return <PayloadKeyValueList payload={payload} />
    }
    return (
        <div className="flex flex-wrap gap-1">
            {hosts.map((host) => (
                <code key={String(host)} className="text-xs px-1 py-0.5 rounded bg-surface-secondary font-mono">
                    {formatPrimitive(host)}
                </code>
            ))}
        </div>
    )
}

/** Pick the kind-specific payload renderer, defaulting to the generic key-value list. */
function PayloadRenderer({ kind, payload }: { kind: string; payload: Record<string, unknown> }): JSX.Element | null {
    if (kind === 'sdk_outdated') {
        return <SdkOutdatedPayload payload={payload} />
    }
    if (kind === 'partial_proxy') {
        return <PartialProxyPayload payload={payload} />
    }
    return <PayloadKeyValueList payload={payload} />
}

export function HealthCheckSignalCard({ signal }: SignalCardProps): JSX.Element {
    const extra = signal.extra as Record<string, unknown> & HealthCheckSignalExtraApi

    const severityTag = (
        <LemonTag size="small" type={SEVERITY_TAG_TYPE[extra.severity]}>
            {capitalize(extra.severity)}
        </LemonTag>
    )

    const body = signal.content || ''
    const summary = extra.summary || ''
    // Avoid printing the summary twice when content already equals it.
    const showSummaryFallback = !body && !!summary
    const markdownText = body || (showSummaryFallback ? summary : '')

    return (
        <SignalCardShell signal={signal} label={extra.title} rightSlot={severityTag}>
            <div className="flex flex-col gap-2">
                <div>
                    <LemonTag size="small" type="muted">
                        {kindLabel(extra.kind)}
                    </LemonTag>
                </div>

                {markdownText && (
                    <LemonMarkdown className="text-sm text-secondary" disableImages>
                        {markdownText}
                    </LemonMarkdown>
                )}

                <PayloadRenderer kind={extra.kind} payload={extra.payload} />

                <div className="flex items-center gap-2 pt-1">
                    <span className="flex-1" />
                    <Link to={extra.link} className="text-xs font-medium">
                        Open in PostHog
                    </Link>
                    <span className="text-xs text-tertiary">
                        <TZLabel time={signal.timestamp} />
                    </span>
                </div>
            </div>
        </SignalCardShell>
    )
}

export const healthCheckSignalCardEntry: SignalCardEntry = {
    key: 'health_checks',
    matches: (signal) => signal.source_product === 'health_checks' && isHealthCheckExtra(signal.extra),
    Component: HealthCheckSignalCard,
}
