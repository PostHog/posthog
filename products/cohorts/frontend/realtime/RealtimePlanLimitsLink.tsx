import posthog from 'posthog-js'

import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

/** Where a project's realtime cohorts reached a limit of its plan, the link to the plans that raise it. */
export function RealtimePlanLimitsLink({
    limit,
    location,
}: {
    limit: 'cohorts' | 'history_days'
    location: 'cohort_page' | 'cohort_create' | 'flag_editor'
}): JSX.Element {
    return (
        <Link
            to={urls.organizationBilling()}
            // pinned: analytics event name and properties, because insights that count clicks read them
            onClick={() => posthog.capture('cohort realtime plan limits clicked', { limit, location })}
            data-attr="cohort-realtime-plan-limits"
        >
            See plan limits
        </Link>
    )
}
