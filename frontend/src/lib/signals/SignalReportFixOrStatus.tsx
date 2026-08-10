import { Tooltip } from '@posthog/lemon-ui'

import type { SignalReportApi } from 'products/signals/frontend/generated/api.schemas'
import {
    STATUS_LABELS,
    STATUS_TOOLTIPS,
} from 'products/signals/frontend/inbox/components/badges/SignalReportStatusBadge'
import type { SignalReportStatus } from 'products/signals/frontend/inbox/types'
import { parsePrUrlParts, safeHttpUrl } from 'products/signals/frontend/inbox/utils/reportPresentation'

import { derivePrState, type PrBadgeState } from './prState'
import { PrBadge } from './SignalReportPrBadge'

/** The inbox's own labels are written to stand alone in a badge, so this surface phrases the same
 * states as a sentence a teammate can act on. The state derivation stays shared. */
const FIX_LABEL: Record<PrBadgeState, string> = {
    open: 'Fix proposed',
    merged: 'Fix merged',
    closed: 'Fix closed',
}

export interface ReportFix {
    label: string
    prUrl: string
    prNumber: string
    state: PrBadgeState
}

/**
 * The pull request a report opened, when it has one that parses as a canonical GitHub PR URL.
 *
 * Whether it shipped is what someone looking at the thing a report came from most needs, so every
 * surface leads with this and falls back to the report's own status. Exported so the surfaces that
 * compose their own layout still spell the states the same way.
 */
export function reportFix(report: SignalReportApi): ReportFix | null {
    // The URL comes from an agent's raw task-run output and isn't scheme-validated server-side.
    const prUrl = safeHttpUrl(report.implementation_pr_url)
    const prNumber = prUrl ? parsePrUrlParts(prUrl)?.number : undefined
    if (!prUrl || !prNumber) {
        return null
    }
    const state = derivePrState(report.status, report.implementation_pr_merged)
    return { label: FIX_LABEL[state], prUrl, prNumber, state }
}

/** The report's own status, phrased the way the inbox badge phrases it. */
export function reportStatusLabel(report: SignalReportApi): string {
    return STATUS_LABELS[report.status as SignalReportStatus] ?? report.status
}

/**
 * The fix a report opened, or its status when there is no pull request to point at.
 *
 * `PrBadge` brings the link, state colour, and the external-link and accessibility handling the inbox
 * already got right.
 */
export function SignalReportFixOrStatus({ report }: { report: SignalReportApi }): JSX.Element {
    const fix = reportFix(report)
    if (fix) {
        return (
            <div className="flex items-center gap-1.5">
                <span className="text-xs font-semibold">{fix.label}</span>
                <PrBadge prNumber={fix.prNumber} prUrl={fix.prUrl} state={fix.state} />
            </div>
        )
    }
    const statusKey = report.status as SignalReportStatus
    // The inbox badge always explains itself on hover, falling back to the label; match that.
    return (
        <Tooltip title={STATUS_TOOLTIPS[statusKey] ?? reportStatusLabel(report)}>
            <span className="text-xs text-muted-alt">{reportStatusLabel(report)}</span>
        </Tooltip>
    )
}
