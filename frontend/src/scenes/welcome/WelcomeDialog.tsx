import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { userLogic } from 'scenes/userLogic'

import { PopularDashboardsCard } from './cards/PopularDashboardsCard'
import { ProductsInUseCard } from './cards/ProductsInUseCard'
import { RecentActivityCard } from './cards/RecentActivityCard'
import { SuggestedNextStepsCard } from './cards/SuggestedNextStepsCard'
import { TeamMembersCard } from './cards/TeamMembersCard'
import { welcomeDialogLogic } from './welcomeDialogLogic'

export function WelcomeDialog(): JSX.Element | null {
    const { welcomeData, welcomeDataLoading, organizationName, inviter, shouldShowDialog } =
        useValues(welcomeDialogLogic)
    const { dismissWelcome, closeDialog } = useActions(welcomeDialogLogic)
    const { user } = useValues(userLogic)

    if (!shouldShowDialog) {
        return null
    }

    const firstName = user?.first_name || ''
    const inviterLine = inviter
        ? `${inviter.name} invited you — welcome${firstName ? `, ${firstName}` : ''}.`
        : `Welcome${firstName ? `, ${firstName}` : ''}.`

    return (
        <LemonModal
            isOpen={shouldShowDialog}
            onClose={() => closeDialog()}
            width={640}
            title={`Welcome to ${organizationName || 'your workspace'}`}
            description={inviterLine}
            data-attr="welcome-dialog"
            footer={
                <div className="flex flex-row justify-between items-center w-full">
                    <LemonButton type="tertiary" onClick={() => closeDialog()} data-attr="welcome-close">
                        I'll look around
                    </LemonButton>
                    <LemonButton type="primary" onClick={() => dismissWelcome()} data-attr="welcome-dismiss">
                        Got it, don't show again
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
                    <p className="text-muted text-sm m-0">
                        Here's a quick orientation to what your teammates have been up to.
                    </p>
                    <TeamMembersCard />
                    <RecentActivityCard />
                    <PopularDashboardsCard />
                    <ProductsInUseCard />
                    <SuggestedNextStepsCard />
                </div>
            )}
        </LemonModal>
    )
}
