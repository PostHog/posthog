import { dayjs } from 'lib/dayjs'
import { uniqueBy } from 'lib/utils/arrays'
import { reverseColonDelimitedDuration, colonDelimitedDuration } from 'lib/utils/durations'
import { urls } from 'scenes/urls'

import type { InsightShortId } from '~/types'

import { type SignalNodeApi } from 'products/signals/frontend/generated/api.schemas'
import { safeHttpUrl } from 'products/signals/frontend/inbox/utils/reportPresentation'
import { conversationsTicketUrl, genericSignalLink } from 'products/signals/frontend/inbox/utils/signalLinks'

import { githubFileUrl, isPullRequest, signalCodeFile, signalExtra, textOf } from './todaySignalText'

export type TodaySignalDestination =
    | { kind: 'recording'; sessionId: string; startAt: number | null; offset: string | null }
    | { kind: 'link'; to: string; external: boolean; label: string }
    | { kind: 'read' }

const PLAYER_LEAD_IN_SECONDS = 5
const SLACK_LINK = /https?:\/\/[\w.-]*slack\.com\/\S+/i

export function newestFirst(signals: SignalNodeApi[]): SignalNodeApi[] {
    return [...signals].sort(
        (first, second) => new Date(second.timestamp).getTime() - new Date(first.timestamp).getTime()
    )
}

export function distinctEvidenceCount(signals: SignalNodeApi[]): number {
    return new Set(signals.map((signal) => `${signal.source_product}:${signal.source_id}`)).size
}

function evidenceItem(signal: SignalNodeApi): string {
    const alert = signal.source_product === 'analytics' ? textOf(signalExtra(signal).alert_id) : null
    return alert ? `analytics:alert:${alert}` : `${signal.source_product}:${signal.source_id}`
}

export function pickEvidence(signals: SignalNodeApi[], count: number): SignalNodeApi[] {
    const unique = uniqueBy(newestFirst(signals), evidenceItem)
    const leads = uniqueBy(unique, (signal) => signal.source_product)
    const rest = unique.filter((signal) => !leads.includes(signal))
    return newestFirst([...leads, ...rest].slice(0, count))
}

function recordingOffsetSeconds(extra: Record<string, unknown>): number | null {
    if (typeof extra.start_time === 'number' && Number.isFinite(extra.start_time)) {
        return extra.start_time
    }
    if (typeof extra.start_time === 'string') {
        return reverseColonDelimitedDuration(extra.start_time)
    }
    return null
}

function playerStart(extra: Record<string, unknown>, offset: number | null): number | null {
    const recordingStart = textOf(extra.recording_start_time) ?? textOf(extra.session_start_time)
    if (offset === null || !recordingStart) {
        return null
    }
    return dayjs(recordingStart)
        .add(Math.max(offset - PLAYER_LEAD_IN_SECONDS, 0), 'second')
        .valueOf()
}

type DestinationSignal = Pick<SignalNodeApi, 'source_product' | 'source_type' | 'source_id' | 'content' | 'extra'>
type SourceLink = (signal: DestinationSignal, extra: Record<string, unknown>) => TodaySignalDestination | null

function link(to: string | null, label: string, external: boolean): TodaySignalDestination | null {
    return to ? { kind: 'link', to, external, label } : null
}

function recording(_: DestinationSignal, extra: Record<string, unknown>): TodaySignalDestination | null {
    const sessionId = textOf(extra.session_id)
    if (!sessionId) {
        return null
    }
    const offset = recordingOffsetSeconds(extra)
    return {
        kind: 'recording',
        sessionId,
        startAt: playerStart(extra, offset),
        offset: offset !== null ? colonDelimitedDuration(offset, 2) : null,
    }
}

function errorIssue(signal: DestinationSignal, extra: Record<string, unknown>): TodaySignalDestination | null {
    const fingerprint = textOf(extra.fingerprint)
    const to = signal.source_id ? urls.errorTrackingIssue(signal.source_id, fingerprint ? { fingerprint } : {}) : null
    return link(to, 'Open issue', false)
}

function analyticsView(_: DestinationSignal, extra: Record<string, unknown>): TodaySignalDestination | null {
    const notebook = textOf(extra.notebook_short_id)
    const insight = textOf(extra.insight_short_id)
    return (
        link(notebook && urls.notebook(notebook), 'Open investigation', false) ??
        link(insight && urls.insightView(insight as InsightShortId), 'Open insight', false)
    )
}

function scoutSource(signal: DestinationSignal): TodaySignalDestination | null {
    const file = signalCodeFile(signal)
    const shortFinding = signal.content.length <= 240
    return (
        link(signalSlackThread(signal), 'Open thread', true) ??
        link(file && shortFinding ? githubFileUrl(file) : null, 'Open file', true)
    )
}

const SOURCE_LINKS: Record<string, SourceLink> = {
    replay_vision: recording,
    session_replay: recording,
    error_tracking: errorIssue,
    conversations: (signal) =>
        link(conversationsTicketUrl({ source_id: signal.source_id, extra: signal.extra }), 'Open ticket', false),
    analytics: analyticsView,
    github: (signal, extra) =>
        link(
            safeHttpUrl(textOf(extra.html_url) ?? ''),
            isPullRequest(signal) ? 'Open pull request' : 'Open issue',
            true
        ),
    signals_scout: scoutSource,
}

export function signalDestination(signal: DestinationSignal): TodaySignalDestination {
    const extra = signalExtra(signal)
    const own = SOURCE_LINKS[signal.source_product]?.(signal, extra)
    if (own) {
        return own
    }
    const generic = genericSignalLink({ source_product: signal.source_product, source_id: signal.source_id, extra })
    return link(generic?.to ?? null, 'Open', generic?.external ?? false) ?? { kind: 'read' }
}

export function signalSlackThread(signal: Pick<SignalNodeApi, 'source_product' | 'content'>): string | null {
    const thread = signal.source_product === 'signals_scout' ? signal.content.match(SLACK_LINK)?.[0] : null
    return thread ? safeHttpUrl(thread.replace(/[).,]+$/, '')) : null
}

export function citedSource(
    signal: Pick<SignalNodeApi, 'source_product' | 'source_id' | 'content'>
): 'code' | 'slack' | null {
    if (signalCodeFile(signal)) {
        return 'code'
    }
    return signalSlackThread(signal) ? 'slack' : null
}
