import { useActions, useValues } from 'kea'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

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
    const { postHogAISetupAvailable } = useValues(catalogSetupLogic)
    const { dismissSetupBanner, reportSetupBannerShown } = useActions(catalogSetupLogic)

    useOnMountEffect(reportSetupBannerShown)

    return (
        <LemonBanner type="ai" onClose={dismissSetupBanner}>
            <div className="flex flex-col gap-2 @2xl:flex-row @2xl:items-center @2xl:justify-between">
                <div>
                    <div className="font-semibold">
                        {postHogAISetupAvailable
                            ? 'Let PostHog AI draft your catalog'
                            : 'Draft your catalog with an AI agent'}
                    </div>
                    <div className="font-normal">
                        It proposes metrics from the insights and dashboards your team uses most. Agents can use a
                        proposed metric, with a warning, until someone on your team approves it.
                    </div>
                </div>
                <div className="flex flex-wrap gap-2 shrink-0">
                    {postHogAISetupAvailable && <SetupWithPostHogAIButton source="banner" />}
                    <CopyAgentSetupPromptButton source="banner" />
                </div>
            </div>
        </LemonBanner>
    )
}
