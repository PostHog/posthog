import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconCheckCircle, IconGithub } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import api from 'lib/api'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { onboardingEventUsageLogic } from 'scenes/onboarding/onboardingEventUsageLogic'

/**
 * Offers GitHub on the install step, ahead of the setup agent asking for it.
 *
 * Installing the GitHub App on an organization the user does not own needs a GitHub owner to
 * approve it, which can take days. The agent only reaches that question partway through its run, so
 * today the wait starts whenever someone sits down to run the command. Asking at the top of the step
 * starts the same approval earlier, against the same integration the agent picks up.
 */
export function SelfDrivingGitHubConnect(): JSX.Element | null {
    const { githubIntegrations, integrationsLoading } = useValues(integrationsLogic)
    const { reportSelfDrivingOnboardingGitHubConnectClicked } = useActions(onboardingEventUsageLogic)

    // Connecting an integration needs project membership (the backend enforces it again). Anyone
    // below that gets the request-access path instead of a button that would fail.
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Member,
    })

    // Hold the space until we know: showing "Connect GitHub" to someone already connected reads as
    // a step they still owe us.
    if (integrationsLoading && githubIntegrations.length === 0) {
        return null
    }

    if (githubIntegrations.length > 0) {
        return (
            <LemonBanner type="success" className="w-full">
                <div className="flex items-center gap-2">
                    <IconCheckCircle className="text-success shrink-0" />
                    <span className="text-sm">
                        GitHub is connected. The setup agent picks it up when you run the command below.
                    </span>
                </div>
            </LemonBanner>
        )
    }

    if (restrictionReason) {
        return <RequestGitHubAccess />
    }

    // Full-page redirect out to GitHub and back to this step. integrationsLogic's OAuth callback
    // creates the integration and reloads the list, so the connected state above renders on return.
    const next = combineUrl(router.values.location.pathname, {
        ...router.values.searchParams,
        step: 'install',
    }).url

    return (
        <div className="flex flex-col gap-2 items-center">
            <p className="text-sm text-muted text-center m-0">
                Connect GitHub so agents can open pull requests. If you are not an owner of your GitHub organization, an
                owner has to approve the install, so starting now means the approval is under way before you run the
                setup agent.
            </p>
            <LemonButton
                type="secondary"
                icon={<IconGithub />}
                to={api.integrations.authorizeUrl({ kind: 'github', next })}
                disableClientSideRouting
                data-attr="self-driving-connect-github"
                onClick={() => reportSelfDrivingOnboardingGitHubConnectClicked()}
            >
                Connect GitHub
            </LemonButton>
        </div>
    )
}

/** For users without project access: the same request that Settings sends, from here. */
function RequestGitHubAccess(): JSX.Element {
    const { accessRequestReason, accessRequestLoading, requestedAccessKinds } = useValues(integrationsLogic)
    const { setAccessRequestReason, requestIntegrationAccess } = useActions(integrationsLogic)
    const { reportSelfDrivingOnboardingGitHubAccessRequested } = useActions(onboardingEventUsageLogic)

    if (requestedAccessKinds.includes('github')) {
        return (
            <LemonBanner type="success" className="w-full">
                Request sent. Your project admins have been notified and can connect GitHub.
            </LemonBanner>
        )
    }

    return (
        <div className="flex flex-col gap-2 w-full">
            <LemonBanner type="info" className="w-full">
                You need more project access to connect GitHub. Tell your project admins why you need it and we will
                email them.
            </LemonBanner>
            <LemonTextArea
                value={accessRequestReason}
                onChange={setAccessRequestReason}
                placeholder="Why does your team need GitHub?"
                minRows={2}
                maxLength={2000}
            />
            <LemonButton
                type="secondary"
                icon={<IconGithub />}
                fullWidth
                center
                loading={accessRequestLoading}
                disabledReason={!accessRequestReason.trim() ? 'Add a short note for your admins' : undefined}
                data-attr="self-driving-request-github-access"
                onClick={() => {
                    reportSelfDrivingOnboardingGitHubAccessRequested()
                    requestIntegrationAccess({ kind: 'github' })
                }}
            >
                Request GitHub
            </LemonButton>
        </div>
    )
}
