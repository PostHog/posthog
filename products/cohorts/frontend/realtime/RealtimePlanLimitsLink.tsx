import posthog from 'posthog-js'

import { Link } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'
import { urls } from 'scenes/urls'

/** Where a project's realtime cohorts reached a limit of its plan, the link to the plans that raise it. */
export function RealtimePlanLimitsLink({
    limit,
    location,
}: {
    limit: 'cohorts' | 'history_days'
    location: 'cohort_page' | 'cohort_create' | 'flag_editor'
}): JSX.Element {
    const quillSurface = useQuillSurface()

    // pinned: analytics event name and properties, because insights that count clicks read them
    const reportClick = (): void => {
        posthog.capture('cohort realtime plan limits clicked', { limit, location })
    }

    if (quillSurface) {
        return (
            <Button
                variant="link"
                size="inline"
                nativeButton={false}
                render={<LinkPrimitive to={urls.organizationBilling()} />}
                onClick={reportClick}
                data-attr="cohort-realtime-plan-limits"
            >
                See plan limits
            </Button>
        )
    }

    return (
        <Link to={urls.organizationBilling()} onClick={reportClick} data-attr="cohort-realtime-plan-limits">
            See plan limits
        </Link>
    )
}
