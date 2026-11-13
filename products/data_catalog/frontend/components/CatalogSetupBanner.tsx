import { useActions, useValues } from 'kea'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import { catalogSetupLogic } from '../catalogSetupLogic'
import { CopyAgentSetupPromptButton } from './CopyAgentSetupPromptButton'
import { SetupWithPostHogAIButton } from './SetupWithPostHogAIButton'

export function CatalogSetupBanner(): JSX.Element | null {
    const { showSetupBanner } = useValues(catalogSetupLogic)

    if (!showSetupBanner) {
        return null
    }
    return <VisibleCatalogSetupBanner />
}

/** Split out so the impression event fires once, when the banner first shows, not on every render. */
function VisibleCatalogSetupBanner(): JSX.Element {
    const { isMaxAvailable } = useValues(maxGlobalLogic)
    const { dismissSetupBanner, reportSetupBannerShown } = useActions(catalogSetupLogic)

    useOnMountEffect(reportSetupBannerShown)

    return (
        <LemonBanner type="ai" onClose={dismissSetupBanner}>
            <div className="flex flex-col gap-2 @2xl:flex-row @2xl:items-center @2xl:justify-between">
                <div>
                    <div className="font-semibold">
                        {isMaxAvailable ? 'Let PostHog AI draft your catalog' : 'Let your agent draft your catalog'}
                    </div>
                    <div className="font-normal">
                        It looks at the insights and dashboards your team uses most and proposes metrics for you to
                        review. Nothing is approved until you approve it.
                    </div>
                </div>
                <div className="flex flex-wrap gap-2 shrink-0">
                    {isMaxAvailable && <SetupWithPostHogAIButton source="banner" />}
                    <CopyAgentSetupPromptButton source="banner" />
                </div>
            </div>
        </LemonBanner>
    )
}
