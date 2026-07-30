import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { SignalReport } from '../../types'

const EXEMPT_TOOLTIPS: Record<string, string> = {
    posthog_health_check:
        "This report was found by PostHog's automated health checks on its own systems, so its PR is free.",
    posthog_onboarding: 'This report was created during your onboarding setup run, so its PR is free.',
}

const EXEMPT_TOOLTIP_DEFAULT = "This report originates from PostHog's own systems, so its PR is free."

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
            <Tooltip title={EXEMPT_TOOLTIPS[report.billing_exempt_reason] ?? EXEMPT_TOOLTIP_DEFAULT}>
                <LemonTag size="small" type="success">
                    Free
                </LemonTag>
            </Tooltip>
        )
    }
    return null
}
