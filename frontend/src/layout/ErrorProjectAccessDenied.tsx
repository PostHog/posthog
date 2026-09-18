import { useValues } from 'kea'
import posthog from 'posthog-js'

import { AccessDenied } from 'lib/components/AccessDenied'
import { NotFound } from 'lib/components/NotFound'
import { CLOUD_HOSTNAMES } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { Link } from 'lib/lemon-ui/Link'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { getAppContext } from 'lib/utils/getAppContext'
import { otherRegionOf, otherRegionSamePathUrl } from 'scenes/authentication/shared/OtherRegionHint'

import { Region } from '~/types'

export function ErrorProjectAccessDenied(): JSX.Element {
    // Staff keep the impersonation shortcut, which NotFound renders from the same app context.
    if (getAppContext()?.suggested_users_with_access) {
        return <NotFound object="project" />
    }

    return <ProjectAccessDenied />
}

function ProjectAccessDenied(): JSX.Element {
    const { preflight } = useValues(preflightLogic)

    // Null off cloud, where there is no other region to point at.
    const region = preflight?.cloud ? preflight.region : null

    useOnMountEffect(() => {
        // pinned: analytics event name and property — renaming breaks dashboards
        posthog.capture('project_access_denied_shown', { region })
    })

    return (
        <AccessDenied
            reason={
                <>
                    <span>This link points to a project you're not a member of.</span>
                    {region ? <OtherRegionSuggestion region={region} /> : null}
                </>
            }
        />
    )
}

function OtherRegionSuggestion({ region }: { region: Region }): JSX.Element {
    const otherRegion = otherRegionOf(region)

    return (
        <span>
            {' '}
            The project may live in our {otherRegion} region. You're signed in to {region}.{' '}
            <Link
                to={otherRegionSamePathUrl(region, window.location)}
                disableClientSideRouting
                data-attr="project-access-denied-other-region"
            >
                Open this page on {CLOUD_HOSTNAMES[otherRegion]}
            </Link>
        </span>
    )
}
