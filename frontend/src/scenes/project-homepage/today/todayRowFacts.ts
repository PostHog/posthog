import { dayjs } from 'lib/dayjs'

import type { SignalReport } from 'products/signals/frontend/inbox/types'

import { type TodayReportState, reportStateLabel } from './todayReportState'

const PULL_REQUEST_FACTS: Record<string, string> = {
    draft: 'Fix in progress',
    open: 'Fix ready for review',
    merged: 'Fix merged',
}

function pullRequestFact(state: string | null | undefined): string | null {
    return state ? (PULL_REQUEST_FACTS[state] ?? null) : null
}

/** A personal ranking reason as a row fact. The other facts are not sentences, so it loses its full stop. */
function personalReasonFact(reason: string | null | undefined): string | null {
    return reason?.trim().replace(/\.$/, '') || null
}

function rowFacts(parts: (string | null | undefined)[]): string[] {
    const shown: string[] = []
    for (const part of parts) {
        if (part && !shown.some((earlier) => earlier.toLowerCase().includes(part.toLowerCase()))) {
            shown.push(part)
        }
    }
    return shown
}

export function reportRowFacts(
    report: SignalReport,
    state: TodayReportState | undefined
): { facts: string[]; reason: string | null } {
    if (state) {
        return { facts: rowFacts([reportStateLabel(state)]), reason: null }
    }
    const reason = personalReasonFact(report.personal_reason)
    return {
        facts: rowFacts([
            pullRequestFact(
                report.implementation_pr_merged
                    ? 'merged'
                    : (report.implementation_pr_state ?? (report.implementation_pr_url ? 'open' : null))
            ),
            reason ? null : `Updated ${dayjs(report.updated_at).fromNow()}`,
        ]),
        reason,
    }
}
