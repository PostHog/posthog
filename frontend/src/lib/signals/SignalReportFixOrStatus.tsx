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

/**
 * Whether it shipped, which is what someone looking at the thing a report came from most needs. A
 * pull request says that better than the report's own status, so the status is the fallback rather
 * than a second badge: either there's no PR, or its URL doesn't parse as one.
 *
 * `PrBadge` brings the link, state colour, and the external-link and accessibility handling the inbox
 * already got right.
 */
export function SignalReportFixOrStatus({ report }: { report: SignalReportApi }): JSX.Element {
    // The URL comes from an agent's raw task-run output and isn't scheme-validated server-side.
    const prUrl = safeHttpUrl(report.implementation_pr_url)
    const prNumber = prUrl ? parsePrUrlParts(prUrl)?.number : undefined
    if (prUrl && prNumber) {
        const state = derivePrState(report.status, report.implementation_pr_merged)
        return (
            <div className="flex items-center gap-1.5">
                <span className="text-xs font-semibold">{FIX_LABEL[state]}</span>
                <PrBadge prNumber={prNumber} prUrl={prUrl} state={state} />
            </div>
        )
    }
    const statusKey = report.status as SignalReportStatus
    const label = STATUS_LABELS[statusKey] ?? report.status
    // The inbox badge always explains itself on hover, falling back to the label; match that.
    return (
        <Tooltip title={STATUS_TOOLTIPS[statusKey] ?? label}>
            <span className="text-xs text-muted-alt">{label}</span>
        </Tooltip>
    )
}
