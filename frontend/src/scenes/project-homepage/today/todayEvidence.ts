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
const RECORDING_SOURCES = new Set(['replay_vision', 'session_replay'])
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

export function signalDestination(
    signal: Pick<SignalNodeApi, 'source_product' | 'source_type' | 'source_id' | 'content' | 'extra'>
): TodaySignalDestination {
    const extra = signalExtra(signal)
    const sessionId = RECORDING_SOURCES.has(signal.source_product) ? textOf(extra.session_id) : null
    if (sessionId) {
        const offset = recordingOffsetSeconds(extra)
        return {
            kind: 'recording',
            sessionId,
            startAt: playerStart(extra, offset),
            offset: offset !== null ? colonDelimitedDuration(offset, 2) : null,
        }
    }
    if (signal.source_product === 'error_tracking' && signal.source_id) {
        const fingerprint = typeof extra.fingerprint === 'string' ? extra.fingerprint : undefined
        return {
            kind: 'link',
            to: urls.errorTrackingIssue(signal.source_id, fingerprint ? { fingerprint } : {}),
            external: false,
            label: 'Open issue',
        }
    }
    if (signal.source_product === 'conversations') {
        const to = conversationsTicketUrl({ source_id: signal.source_id, extra: signal.extra })
        if (to) {
            return { kind: 'link', to, external: false, label: 'Open ticket' }
        }
    }
    if (signal.source_product === 'analytics') {
        const notebook = textOf(extra.notebook_short_id)
        if (notebook) {
            return { kind: 'link', to: urls.notebook(notebook), external: false, label: 'Open investigation' }
        }
        const insight = textOf(extra.insight_short_id)
        if (insight) {
            return {
                kind: 'link',
                to: urls.insightView(insight as InsightShortId),
                external: false,
                label: 'Open insight',
            }
        }
    }
    if (signal.source_product === 'github') {
        const to = safeHttpUrl(textOf(extra.html_url) ?? '')
        if (to) {
            return {
                kind: 'link',
                to,
                external: true,
                label: isPullRequest(signal) ? 'Open pull request' : 'Open issue',
            }
        }
    }
    if (signal.source_product === 'signals_scout') {
        const to = signalSlackThread(signal)
        if (to) {
            return { kind: 'link', to, external: true, label: 'Open thread' }
        }
        const file = signalCodeFile(signal)
        if (file && signal.content.length <= 240) {
            return { kind: 'link', to: githubFileUrl(file), external: true, label: 'Open file' }
        }
    }
    const link = genericSignalLink({ source_product: signal.source_product, source_id: signal.source_id, extra })
    return link ? { kind: 'link', to: link.to, external: link.external, label: 'Open' } : { kind: 'read' }
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
