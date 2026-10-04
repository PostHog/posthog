import { urls } from 'scenes/urls'

import type { InsightShortId } from '~/types'

import { conversationsTicketUrl, genericSignalLink } from 'products/signals/frontend/inbox/utils/signalLinks'
import type { SignalPreviewApi, SignalViewApi } from 'products/today/frontend/generated/api.schemas'

import { textOf } from './todaySignalText'

export type TodaySignalDestination =
    | { kind: 'recording'; sessionId: string; startAt: number | null; offset: string | null }
    | { kind: 'link'; to: string; external: boolean; label: string }
    | { kind: 'read' }

export interface TodayPreviewLink {
    to: string
    external: boolean
    label: string
}

type AppLink = (signal: SignalViewApi) => TodaySignalDestination | null

function link(to: string | null, label: string, external: boolean): TodaySignalDestination | null {
    return to ? { kind: 'link', to, external, label } : null
}

function errorIssue(signal: SignalViewApi): TodaySignalDestination | null {
    const fingerprint = textOf(signal.extra.fingerprint)
    const to = signal.source_id ? urls.errorTrackingIssue(signal.source_id, fingerprint ? { fingerprint } : {}) : null
    return link(to, 'Open issue', false)
}

function analyticsView(signal: SignalViewApi): TodaySignalDestination | null {
    const notebook = textOf(signal.extra.notebook_short_id)
    const insight = textOf(signal.extra.insight_short_id)
    return (
        link(notebook && urls.notebook(notebook), 'Open investigation', false) ??
        link(insight && urls.insightView(insight as InsightShortId), 'Open insight', false)
    )
}

const APP_LINKS: Record<string, AppLink> = {
    error_tracking: errorIssue,
    conversations: (signal) =>
        link(conversationsTicketUrl({ source_id: signal.source_id, extra: signal.extra }), 'Open ticket', false),
    analytics: analyticsView,
}

const PLAYER_LEAD_IN_SECONDS = 5
const OFFSET = /^(\d+):(\d{2})$/

function offsetSeconds(offset: string | null): number | null {
    const match = offset ? OFFSET.exec(offset) : null
    return match ? Number(match[1]) * 60 + Number(match[2]) : null
}

function recordingDestination(recording: NonNullable<SignalViewApi['recording']>): TodaySignalDestination {
    const seconds = offsetSeconds(recording.offset)
    if (!recording.start_at && seconds !== null) {
        const secondsOffsetFromStart = Math.max(seconds - PLAYER_LEAD_IN_SECONDS, 0)
        return {
            kind: 'link',
            to: urls.replaySingle(recording.session_id, { secondsOffsetFromStart }),
            external: false,
            label: `Play at ${recording.offset}`,
        }
    }
    const startAt = recording.start_at ? Date.parse(recording.start_at) : null
    return { kind: 'recording', sessionId: recording.session_id, startAt, offset: recording.offset }
}

export function signalDestination(signal: SignalViewApi): TodaySignalDestination {
    if (signal.recording) {
        return recordingDestination(signal.recording)
    }
    const own =
        link(signal.link?.url ?? null, signal.link?.text ?? '', true) ?? APP_LINKS[signal.source_product]?.(signal)
    if (own) {
        return own
    }
    const generic = genericSignalLink({
        source_product: signal.source_product,
        source_id: signal.source_id,
        extra: signal.extra,
    })
    return link(generic?.to ?? null, 'Open', generic?.external ?? false) ?? { kind: 'read' }
}

export function previewOpen(signal: SignalViewApi, destination: TodaySignalDestination): TodayPreviewLink | null {
    const preview = signal.preview
    if (preview?.link) {
        return { to: preview.link.url, external: true, label: preview.link.text }
    }
    if (destination.kind !== 'link') {
        return null
    }
    return { to: destination.to, external: destination.external, label: preview?.link_label ?? destination.label }
}

export function shownPreview(signal: SignalViewApi, open: TodayPreviewLink | null): SignalPreviewApi | null {
    const preview = signal.preview
    if (!preview) {
        return null
    }
    const hasContent = preview.code.length > 0 || preview.block.length > 0 || !!preview.text
    return hasContent || !open ? preview : null
}
