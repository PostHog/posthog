import { urls } from 'scenes/urls'

import type { EvaluationReportCitation } from '../types'

// Rewrite each cited generation or trace ID in the content into a markdown link
// to the trace viewer. Uses the structured citations list (not regex scanning) so:
// - only ids the agent explicitly cited get linked (no false positives)
// - the trace_id for the correct URL is guaranteed available
// - there's no ReDoS surface on arbitrary prose input
//
// Two-phase placeholder swap prevents double-wrapping when an id is mentioned
// multiple times, and prevents one id's generated link from being re-matched
// by a later citation. Wrapper variants (`uuid`, <uuid>, bare) are collapsed
// in descending specificity so the wrappers themselves get absorbed into the
// replacement rather than surviving around a link.
const SAFE_CITATION_LABEL_RE = /^[A-Za-z0-9._~-]{1,8}$/

function citationLinkLabel(citedId: string, fallbackLabel: string): string {
    const preview = citedId.slice(0, 8)
    return SAFE_CITATION_LABEL_RE.test(preview) ? `${preview}...` : fallbackLabel
}

// $ai_session_id is caller-supplied through ingestion and urls.aiObservabilitySession interpolates
// it into the path raw, so a ">" or ")" in it escapes the Markdown link destination and the rest of
// the ID renders as attacker-controlled Markdown. Only link IDs that can't do that; anything else
// stays plain text. Percent-encoding the session URL is the real fix, but that also has to teach
// the session scene to decode, which is a routing change beyond this.
const LINKABLE_SESSION_ID_RE = /^[A-Za-z0-9._~:@-]+$/

// A citation names the unit that was evaluated: a session, a generation, or a trace. Session
// citations may also carry the trace the agent read inside them, but the link goes to the session.
export type CitationTarget =
    | { kind: 'session'; citedId: string; url: string; label: string }
    | { kind: 'trace'; citedId: string; url: string; label: string; traceId: string; eventId: string | null }

export function citationTarget(c: EvaluationReportCitation): CitationTarget | null {
    if (c.session_id) {
        if (!LINKABLE_SESSION_ID_RE.test(c.session_id)) {
            return null
        }
        return {
            kind: 'session',
            citedId: c.session_id,
            url: urls.aiObservabilitySession(c.session_id),
            label: 'session',
        }
    }
    const citedId = c.generation_id || c.trace_id
    const traceId = c.trace_id || c.generation_id
    if (!citedId || !traceId) {
        return null
    }
    const eventId = c.generation_id && c.trace_id ? c.generation_id : null
    return {
        kind: 'trace',
        citedId,
        url: urls.aiObservabilityTrace(traceId, eventId ? { event: eventId } : undefined),
        label: c.generation_id ? 'generation' : 'trace',
        traceId,
        eventId,
    }
}

export function linkifyCitations(content: string, citations: EvaluationReportCitation[]): string {
    if (citations.length === 0) {
        return content
    }
    const tokens: Array<{ token: string; link: string }> = []
    let out = content
    citations.forEach((c, idx) => {
        const target = citationTarget(c)
        if (!target) {
            return
        }
        const { citedId, url } = target
        const token = `\0CITE${idx}\0`
        // Angle-bracket destination: trace and session IDs are opaque and caller-supplied, and a
        // bare ")" in one would otherwise close the destination early and hijack the rest of the link.
        const link = `[\`${citationLinkLabel(citedId, target.label)}\`](<${url}>)`
        const before = out
        out = out.split(`\`${citedId}\``).join(token)
        out = out.split(`<${citedId}>`).join(token)
        if (c.generation_id) {
            out = out.split(citedId).join(token)
        }
        if (out !== before) {
            tokens.push({ token, link })
        }
    })
    for (const { token, link } of tokens) {
        out = out.split(token).join(link)
    }
    return out
}
