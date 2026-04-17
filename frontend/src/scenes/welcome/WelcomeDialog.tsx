import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { userLogic } from 'scenes/userLogic'

import { AskMaxCard } from './cards/AskMaxCard'
import { PopularDashboardsCard } from './cards/PopularDashboardsCard'
import { ProductsInUseCard } from './cards/ProductsInUseCard'
import { RecentActivityCard } from './cards/RecentActivityCard'
import { SuggestedNextStepsCard } from './cards/SuggestedNextStepsCard'
import { TeamMembersCard } from './cards/TeamMembersCard'
import { welcomeDialogLogic } from './welcomeDialogLogic'

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
    const { dismissWelcome, closeDialog } = useActions(welcomeDialogLogic)
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
        : "You're one of the first in this workspace — start exploring."

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
                    <LemonButton type="tertiary" onClick={() => closeDialog()} data-attr="welcome-close">
                        I'll look around
                    </LemonButton>
                    <LemonButton type="primary" onClick={() => dismissWelcome()} data-attr="welcome-dismiss">
                        Don't show again
                    </LemonButton>
                </div>
            }
        >
            {welcomeDataLoading && !welcomeData.organization_name ? (
                <div className="flex justify-center p-6">
                    <Spinner />
                </div>
            ) : (
                <div className="flex flex-col gap-4">
                    {welcomeDataError ? (
                        <LemonBanner type="warning">
                            We couldn't load your team's activity. You can still explore PostHog from here.
                        </LemonBanner>
                    ) : (
                        <p className="text-muted text-sm m-0">{introCopy}</p>
                    )}
                    <TeamMembersCard />
                    <RecentActivityCard />
                    <PopularDashboardsCard />
                    <ProductsInUseCard />
                    <SuggestedNextStepsCard />
                    <AskMaxCard />
                </div>
            )}
        </LemonModal>
    )
}
