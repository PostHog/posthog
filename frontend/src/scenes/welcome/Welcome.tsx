import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { PopularDashboardsCard } from './cards/PopularDashboardsCard'
import { ProductsInUseCard } from './cards/ProductsInUseCard'
import { RecentActivityCard } from './cards/RecentActivityCard'
import { SuggestedNextStepsCard } from './cards/SuggestedNextStepsCard'
import { TeamMembersCard } from './cards/TeamMembersCard'
import { welcomeSceneLogic } from './welcomeSceneLogic'

export const scene: SceneExport = {
    component: Welcome,
    logic: welcomeSceneLogic,
}

export function Welcome(): JSX.Element {
    const { welcomeData, welcomeDataLoading, organizationName, inviter, primaryCtaLabel } = useValues(welcomeSceneLogic)
    const { dismissWelcome } = useActions(welcomeSceneLogic)
    const { user } = useValues(userLogic)

    if (welcomeDataLoading && !welcomeData.organization_name) {
        return <SpinnerOverlay />
    }

    const firstName = user?.first_name || ''
    const inviterLine = inviter
        ? `${inviter.name} invited you — welcome${firstName ? `, ${firstName}` : ''}.`
        : `Welcome${firstName ? `, ${firstName}` : ''}.`

    return (
        <div className="mx-auto max-w-3xl py-8 px-4 flex flex-col gap-4">
            <LemonCard hoverEffect={false} className="p-6">
                <h1 className="text-2xl font-bold mb-2">Welcome to {organizationName || 'your workspace'}</h1>
                <p className="text-muted text-base">{inviterLine}</p>
                <p className="text-muted mt-2 text-sm">
                    Here's a quick orientation to what your teammates have been up to.
                </p>
            </LemonCard>

            <TeamMembersCard />
            <RecentActivityCard />
            <PopularDashboardsCard />
            <ProductsInUseCard />
            <SuggestedNextStepsCard />

            <div className="flex flex-row justify-between items-center mt-4">
                <LemonButton type="tertiary" onClick={() => dismissWelcome()} data-attr="welcome-dismiss">
                    Dismiss
                </LemonButton>
                <LemonButton type="primary" onClick={() => dismissWelcome()} data-attr="welcome-primary-cta">
                    {primaryCtaLabel}
                </LemonButton>
            </div>
        </div>
    )
}

export default Welcome
