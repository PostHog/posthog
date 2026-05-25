import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { AskMaxCard } from './cards/AskMaxCard'
import { PopularDashboardsCard } from './cards/PopularDashboardsCard'
import { ProductsInUseCard } from './cards/ProductsInUseCard'
import { RecentActivityCard } from './cards/RecentActivityCard'
import { SuggestedNextStepsCard } from './cards/SuggestedNextStepsCard'
import { TeamMembersCard } from './cards/TeamMembersCard'
import { wasWelcomeDismissed, welcomeDialogLogic } from './welcomeDialogLogic'

// The welcome dialog is allowed to auto-open only on these scenes. The welcome flow's purpose
// is to orient an invitee on the home of the product — opening it as an overlay over a deep-link
// to settings, billing, replays, or arbitrary scenes would block the user from the page they
// were trying to reach. Dashboard is included because sceneLogic redirects `/` to the team's
// primary dashboard when one is configured, so first-visit invitees land there instead of home.
const WELCOME_DIALOG_ALLOWED_SCENES = new Set<Scene>([Scene.ProjectHomepage, Scene.Dashboard])

/** Only mount the welcome dialog (and its kea logic) for users actually eligible to see it.
 * Lives in GlobalModals so it can render regardless of which scene the user lands on after
 * signup (project home, primary dashboard, etc.). Scene gating ensures the dialog only auto-opens
 * on the home / primary-dashboard scenes, not over deep-linked settings/billing/replay pages. */
export function MaybeWelcomeDialog(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { sceneId } = useValues(sceneLogic)
    if (!user || user.is_organization_first_user !== false || wasWelcomeDismissed(user.uuid, user.organization?.id)) {
        return null
    }
    if (!sceneId || !WELCOME_DIALOG_ALLOWED_SCENES.has(sceneId as Scene)) {
        return null
    }
    return <WelcomeDialog />
}

export function WelcomeDialog(): JSX.Element | null {
    const {
        welcomeData,
        welcomeDataLoading,
        welcomeDataError,
        organizationName,
        inviter,
        shouldShowDialog,
        teamMembers,
        recentActivity,
        popularDashboards,
        productsInUse,
    } = useValues(welcomeDialogLogic)
    const { dismissWelcome, closeDialog, loadWelcomeData } = useActions(welcomeDialogLogic)
    const { user } = useValues(userLogic)

    if (!shouldShowDialog) {
        return null
    }

    const firstName = user?.first_name || ''
    const inviterLine = inviter
        ? `${inviter.name} invited you. Welcome${firstName ? `, ${firstName}` : ''}!`
        : firstName
          ? `Welcome, ${firstName}!`
          : undefined

    const hasAnyData =
        teamMembers.length > 0 || recentActivity.length > 0 || popularDashboards.length > 0 || productsInUse.length > 0
    const introCopy = hasAnyData
        ? "Here's what your team has been working on."
        : "You're one of the first in this organization — start exploring."

    return (
        <LemonModal
            isOpen={shouldShowDialog}
            onClose={() => closeDialog()}
            width={640}
            title={`Welcome to ${organizationName || 'PostHog'}`}
            description={inviterLine}
            data-attr="welcome-dialog"
            footer={
                <div className="flex flex-row justify-between items-center w-full">
                    <LemonButton type="tertiary" onClick={() => dismissWelcome()} data-attr="welcome-dismiss">
                        Don't show again
                    </LemonButton>
                    <LemonButton type="primary" onClick={() => closeDialog()} data-attr="welcome-close">
                        Start exploring
                    </LemonButton>
                </div>
            }
        >
            {welcomeDataLoading && !welcomeData.organization_name ? (
                <div
                    className="flex justify-center p-6"
                    role="status"
                    aria-live="polite"
                    aria-label="Loading welcome content"
                >
                    <Spinner />
                </div>
            ) : (
                <div className="flex flex-col gap-3">
                    {welcomeDataError ? (
                        <LemonBanner
                            type="warning"
                            action={{
                                children: 'Try again',
                                onClick: () => loadWelcomeData(),
                            }}
                        >
                            We couldn't load your team's activity. You can still explore PostHog from here.
                        </LemonBanner>
                    ) : (
                        <p className="text-muted text-sm m-0">{introCopy}</p>
                    )}
                    {/* Quick orientation first: products in use, AI helper, suggested next steps. */}
                    <ProductsInUseCard />
                    <AskMaxCard />
                    <SuggestedNextStepsCard />
                    {/* Then deeper context about what's been happening. */}
                    <RecentActivityCard />
                    <PopularDashboardsCard />
                    <TeamMembersCard />
                </div>
            )}
        </LemonModal>
    )
}
