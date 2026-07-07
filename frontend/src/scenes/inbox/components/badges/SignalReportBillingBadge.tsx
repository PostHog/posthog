import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { SignalReport } from '../../types'

function refundTooltip(refund: NonNullable<SignalReport['refund']>): string {
    if (refund.billing_path === 'excluded') {
        return "This PR was refunded before it was ever billed – you won't pay for it and it doesn't count toward your included PRs."
    }
    if (refund.credit_amount_usd != null) {
        return `This PR was refunded – $${refund.credit_amount_usd} was credited toward your next invoice and it doesn't count toward your included PRs.`
    }
    return "This PR was refunded – the credit is being processed and it doesn't count toward your included PRs."
}

/**
 * Permanent billing marker for a report: "Refunded" once its PR has been refunded, or "Free" when
 * the report is system-marked never-billable (PostHog-system origin, e.g. a health-check scout
 * finding). Null for ordinary billable reports.
 */
export function SignalReportBillingBadge({ report }: { report: SignalReport }): JSX.Element | null {
    if (report.refund) {
        return (
            <Tooltip title={refundTooltip(report.refund)}>
                <LemonTag size="small" type="completion">
                    Refunded
                </LemonTag>
            </Tooltip>
        )
    }
    if (report.billing_exempt_reason) {
        return (
            <Tooltip title="This report comes from checks PostHog runs on its own systems, so its PR is free.">
                <LemonTag size="small" type="success">
                    Free
                </LemonTag>
            </Tooltip>
        )
    }
    return null
}
