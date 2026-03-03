import clsx from 'clsx'
import { useState } from 'react'

import { IconChevronRight, IconExternal } from '@posthog/icons'
import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import ViewRecordingButton, { RecordingPlayerType } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { sourceProductColor } from 'scenes/debug/signals/helpers'
import type { SignalNode } from 'scenes/debug/signals/types'

interface SessionReplaySegment {
    session_id: string
    start_time: string
    end_time: string
    distinct_id: string
    content: string
}

interface SessionReplaySignalExtra {
    label_title: string
    actionable: boolean
    segments: SessionReplaySegment[]
    metrics: { relevant_user_count: number; active_users_in_period: number; occurrence_count: number }
}

interface GithubIssueSignalExtra {
    html_url: string
    number: number
    labels: string[]
    created_at: string
    updated_at: string
    state: string
}

interface ZendeskTicketSignalExtra {
    url: string
    type: string
    tags: string[]
    created_at: string
    priority: string
    status: string
}

interface LlmEvalSignalExtra {
    evaluation_id: string
    target_event_id: string
    target_event_type: string
    trace_id: string
    model: string
    provider: string
}

export function SignalCard({ signal }: { signal: SignalNode }): JSX.Element {
    if (isSessionReplayExtra(signal.extra)) {
        return <SessionReplaySignalCard signal={signal} extra={signal.extra} />
    }
    if (isGithubIssueExtra(signal.extra)) {
        return <GithubIssueSignalCard signal={signal} extra={signal.extra} />
    }
    if (isZendeskTicketExtra(signal.extra)) {
        return <ZendeskTicketSignalCard signal={signal} extra={signal.extra} />
    }
    if (isLlmEvalExtra(signal.extra)) {
        return <LlmEvalSignalCard signal={signal} extra={signal.extra} />
    }
    return <GenericSignalCard signal={signal} />
}

function SessionReplaySignalCard({
    signal,
    extra,
}: {
    signal: SignalNode
    extra: SessionReplaySignalExtra
}): JSX.Element {
    const [showAllSegments, setShowAllSegments] = useState(false)
    const maxVisible = 3
    const visibleSegments = showAllSegments ? extra.segments : extra.segments.slice(0, maxVisible)

    return (
        <div className="border rounded p-3 bg-surface-primary">
            <SignalCardHeader signal={signal} label={extra.label_title} />

            {signal.content && <LemonMarkdown className="text-sm text-secondary mb-2">{signal.content}</LemonMarkdown>}

            <div className="flex items-center gap-2 text-xs text-tertiary mb-3">
                {extra.metrics.occurrence_count > 0 && (
                    <span>
                        {extra.metrics.occurrence_count}{' '}
                        {extra.metrics.occurrence_count === 1 ? 'occurrence' : 'occurrences'}
                    </span>
                )}
                {extra.metrics.relevant_user_count > 0 && (
                    <span>
                        {extra.metrics.relevant_user_count} affected{' '}
                        {extra.metrics.relevant_user_count === 1 ? 'user' : 'users'}
                    </span>
                )}
                <LemonTag size="small" type={extra.actionable ? 'success' : 'muted'}>
                    {extra.actionable ? 'Actionable' : 'Not actionable'}
                </LemonTag>
            </div>

            {extra.segments.length > 0 && (
                <>
                    <div className="border-t pt-2 mt-2">
                        <span className="text-xs font-medium text-tertiary">Session segments</span>
                    </div>
                    <div className="space-y-2 mt-2">
                        {visibleSegments.map((segment, i) => (
                            <div key={i} className="border rounded p-2 bg-surface-secondary">
                                <div className="flex items-start gap-2">
                                    <LemonMarkdown className="text-sm text-secondary flex-1 line-clamp-2">
                                        {segment.content}
                                    </LemonMarkdown>
                                    <ViewRecordingButton
                                        sessionId={segment.session_id}
                                        timestamp={segment.start_time}
                                        openPlayerIn={RecordingPlayerType.Modal}
                                        size="xsmall"
                                        type="secondary"
                                        label="Play"
                                    />
                                </div>
                                <div className="flex items-center gap-1.5 mt-1 text-xs text-tertiary">
                                    <span className="font-mono">{segment.distinct_id.slice(0, 10)}...</span>
                                    <span>·</span>
                                    <span>
                                        {humanFriendlyDetailedTime(segment.start_time)} –{' '}
                                        {humanFriendlyDetailedTime(segment.end_time)}
                                    </span>
                                </div>
                            </div>
                        ))}
                    </div>
                    {extra.segments.length > maxVisible && (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            className="mt-1"
                            onClick={() => setShowAllSegments(!showAllSegments)}
                        >
                            {showAllSegments ? 'Show fewer' : `Show all ${extra.segments.length} segments`}
                        </LemonButton>
                    )}
                </>
            )}
        </div>
    )
}

function GithubIssueSignalCard({ signal, extra }: { signal: SignalNode; extra: GithubIssueSignalExtra }): JSX.Element {
    return (
        <div className="border rounded p-3 bg-surface-primary">
            <SignalCardHeader signal={signal} />

            {signal.content && <LemonMarkdown className="text-sm text-secondary mb-2">{signal.content}</LemonMarkdown>}

            <div className="flex items-center gap-2 flex-wrap text-xs text-tertiary">
                <span className="font-medium">#{extra.number}</span>
                {Array.isArray(extra.labels) &&
                    extra.labels.map((label) => (
                        <LemonTag key={label} size="small">
                            {label}
                        </LemonTag>
                    ))}
                <span className="flex-1" />
                <Link to={extra.html_url} target="_blank" className="flex items-center gap-1 text-xs">
                    View on GitHub <IconExternal className="size-3" />
                </Link>
            </div>
            <div className="text-xs text-tertiary mt-1">Opened: {humanFriendlyDetailedTime(extra.created_at)}</div>
        </div>
    )
}

function ZendeskTicketSignalCard({
    signal,
    extra,
}: {
    signal: SignalNode
    extra: ZendeskTicketSignalExtra
}): JSX.Element {
    return (
        <div className="border rounded p-3 bg-surface-primary">
            <SignalCardHeader signal={signal} />

            {signal.content && <LemonMarkdown className="text-sm text-secondary mb-2">{signal.content}</LemonMarkdown>}

            <div className="flex items-center gap-2 flex-wrap text-xs text-tertiary">
                <LemonTag size="small">Priority: {extra.priority}</LemonTag>
                <LemonTag size="small">Status: {extra.status}</LemonTag>
                {Array.isArray(extra.tags) &&
                    extra.tags.map((tag) => (
                        <LemonTag key={tag} size="small" type="muted">
                            {tag}
                        </LemonTag>
                    ))}
                <span className="flex-1" />
                <Link to={extra.url} target="_blank" className="flex items-center gap-1 text-xs">
                    Open <IconExternal className="size-3" />
                </Link>
            </div>
        </div>
    )
}

function LlmEvalSignalCard({ signal, extra }: { signal: SignalNode; extra: LlmEvalSignalExtra }): JSX.Element {
    return (
        <div className="border rounded p-3 bg-surface-primary">
            <SignalCardHeader signal={signal} />

            {signal.content && <LemonMarkdown className="text-sm text-secondary mb-2">{signal.content}</LemonMarkdown>}

            <div className="flex items-center gap-2 text-xs text-tertiary">
                <span>Model: {extra.model}</span>
                <span>·</span>
                <span>Provider: {extra.provider}</span>
            </div>
            <div className="text-xs text-tertiary mt-1">
                Trace: <span className="font-mono">{extra.trace_id.slice(0, 12)}...</span>
            </div>
        </div>
    )
}

function GenericSignalCard({ signal }: { signal: SignalNode }): JSX.Element {
    const [showRaw, setShowRaw] = useState(false)

    return (
        <div className="border rounded p-3 bg-surface-primary">
            <SignalCardHeader signal={signal} />

            {signal.content && <LemonMarkdown className="text-sm text-secondary mb-2">{signal.content}</LemonMarkdown>}

            <div className="text-xs text-tertiary">
                <TZLabel time={signal.timestamp} />
            </div>

            {Object.keys(signal.extra).length > 0 && (
                <div className="mt-2">
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        onClick={() => setShowRaw(!showRaw)}
                        icon={
                            <IconChevronRight className={clsx('size-3 transition-transform', showRaw && 'rotate-90')} />
                        }
                    >
                        Raw metadata
                    </LemonButton>
                    {showRaw && (
                        <pre className="text-xs mt-1 p-2 bg-surface-secondary rounded overflow-x-auto max-h-60">
                            {JSON.stringify(signal.extra, null, 2)}
                        </pre>
                    )}
                </div>
            )}
        </div>
    )
}

function SignalCardHeader({ signal, label }: { signal: SignalNode; label?: string }): JSX.Element {
    return (
        <div className="flex items-center gap-2 mb-2">
            <span
                className="size-2.5 rounded-full shrink-0"
                style={{ backgroundColor: sourceProductColor(signal.source_product) }}
            />
            <span className="text-xs font-medium text-tertiary">
                {signal.source_product} / {signal.source_type}
            </span>
            {label && <span className="text-xs font-medium text-primary flex-1 truncate">{label}</span>}
            <LemonTag size="small" className="shrink-0">
                Weight: {signal.weight.toFixed(1)}
            </LemonTag>
        </div>
    )
}

function isSessionReplayExtra(
    extra: Record<string, unknown>
): extra is Record<string, unknown> & SessionReplaySignalExtra {
    return 'segments' in extra && Array.isArray(extra.segments)
}

function isGithubIssueExtra(extra: Record<string, unknown>): extra is Record<string, unknown> & GithubIssueSignalExtra {
    return 'html_url' in extra && 'number' in extra
}

function isZendeskTicketExtra(
    extra: Record<string, unknown>
): extra is Record<string, unknown> & ZendeskTicketSignalExtra {
    return 'url' in extra && 'priority' in extra
}

function isLlmEvalExtra(extra: Record<string, unknown>): extra is Record<string, unknown> & LlmEvalSignalExtra {
    return 'evaluation_id' in extra && 'trace_id' in extra
}
