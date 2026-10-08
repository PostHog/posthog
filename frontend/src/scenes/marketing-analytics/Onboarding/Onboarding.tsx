import { useActions, useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { detectedSourcesLogic } from 'products/marketing_analytics/frontend/dashboard/detectedSourcesLogic'
import { SearchConsoleSource } from 'products/marketing_analytics/frontend/dashboard/SearchConsoleSource'
import { SourceOnboardingScan } from 'products/marketing_analytics/frontend/dashboard/SourceOnboardingScan'

import { MarketingAnalyticsSourceStatusBanner } from '../../web-analytics/tabs/marketing-analytics/frontend/components/MarketingAnalyticsSourceStatusBanner'
import { marketingAnalyticsLogic } from '../../web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { setupPlanLogic } from '../../web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'
import { AddSourceStep } from './AddSourceStep'
import { marketingOnboardingLogic } from './marketingOnboardingLogic'

export function Onboarding({ completeOnboarding }: { completeOnboarding: () => void }): JSX.Element {
    const { reportMarketingAnalyticsOnboardingViewed, reportMarketingAnalyticsOnboardingCompleted } =
        useActions(eventUsageLogic)
    const { addProductIntent } = useActions(teamLogic)
    const { currentTeamId } = useValues(teamLogic)
    useValues(detectedSourcesLogic({ teamId: currentTeamId ?? 0 }))
    const { setupPlan, setupPlanLoading, visibleSuggestions, sourceScanDisabledReason } = useValues(setupPlanLogic)
    const { rescanSources } = useActions(setupPlanLogic)
    const { showManualSources } = useValues(marketingOnboardingLogic)
    const { setShowManualSources } = useActions(marketingOnboardingLogic)
    const { hasSources } = useValues(marketingAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const sourceOnboardingEnabled = !!featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_SOURCE_ONBOARDING]

    useOnMountEffect(() => {
        reportMarketingAnalyticsOnboardingViewed()
    })

    const handleComplete = (): void => {
        reportMarketingAnalyticsOnboardingCompleted(hasSources)
        addProductIntent({
            product_type: ProductKey.MARKETING_ANALYTICS,
            intent_context: ProductIntentContext.MARKETING_ANALYTICS_ONBOARDING_COMPLETED,
            metadata: { has_sources: hasSources },
        })
        completeOnboarding()
    }

    return (
        <div className="space-y-4">
            <MarketingAnalyticsSourceStatusBanner />
            {!sourceOnboardingEnabled || showManualSources ? (
                <AddSourceStep
                    onContinue={handleComplete}
                    hasSources={hasSources}
                    onBack={sourceOnboardingEnabled ? () => setShowManualSources(false) : undefined}
                />
            ) : (
                <SourceOnboardingScan
                    loading={setupPlanLoading && !setupPlan}
                    failed={!setupPlan && !setupPlanLoading}
                    suggestions={visibleSuggestions.filter(
                        (suggestion) =>
                            suggestion.kind === 'connect_source' && suggestion.apply?.op === 'open_source_wizard'
                    )}
                    onManual={() => setShowManualSources(true)}
                    onContinue={handleComplete}
                    onRescan={rescanSources}
                    rescanLoading={setupPlanLoading}
                    rescanDisabledReason={sourceScanDisabledReason}
                />
            )}
            <SearchConsoleSource />
        </div>
    )
}
