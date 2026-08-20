import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { IntegrationSettingsModal } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/settings/IntegrationSettingsModal'
import {
    SetupSection,
    marketingAnalyticsLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { marketingAnalyticsSettingsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsSettingsLogic'
import type { Suggestion } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'
import { setupPlanLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { runNavigateOp } from './navigateOps'
import { suggestionsForSection } from './sectionRouting'
import { SectionSuggestions } from './SectionSuggestions'
import { SETUP_SECTIONS } from './setupSections'
import { SuggestionModal } from './SuggestionModal'

/** Count of open suggestions in a section, and whether any of them is blocking.
 * Shown in the nav so you can see where the problems are without opening each one. */
function SectionBadge({
    suggestions,
    section,
}: {
    suggestions: Suggestion[]
    section: SetupSection
}): JSX.Element | null {
    const forSection = suggestionsForSection(suggestions, section)
    if (!forSection.length) {
        return null
    }
    const hasError = forSection.some((suggestion) => suggestion.severity === 'error')
    return (
        <LemonTag type={hasError ? 'danger' : 'warning'} size="small">
            {forSection.length}
        </LemonTag>
    )
}

export function SetupTab(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { setupSection } = useValues(marketingAnalyticsLogic)
    const { setSetupSection } = useActions(marketingAnalyticsLogic)
    const { setupPlan, visibleSuggestions, reviewingSuggestion, isReviewingBatch, safeBatch, applyingIds } =
        useValues(setupPlanLogic)
    const { loadSetupPlan, reviewSuggestion, confirmReviewedSuggestion, confirmReviewedBatch } =
        useActions(setupPlanLogic)
    const { integrationSettingsModal } = useValues(marketingAnalyticsSettingsLogic)
    const { closeIntegrationSettingsModal } = useActions(marketingAnalyticsSettingsLogic)

    // Keep the audit gated for one release so the two flags can roll independently;
    // drop this once Setup is the only way in.
    const sections = SETUP_SECTIONS.filter(
        (section) =>
            section.key !== SetupSection.INTEGRATION_HEALTH || featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_UTM_AUDIT]
    )

    // Once on arrival and never again on its own — the plan is six ClickHouse queries
    // deep, one unioning every ad adapter.
    useEffect(() => {
        if (!setupPlan) {
            loadSetupPlan()
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    const active = sections.find((section) => section.key === setupSection) ?? sections[0]

    return (
        <div className="flex flex-col md:flex-row gap-6 mt-4">
            <nav className="md:w-56 shrink-0 flex flex-row md:flex-col gap-px overflow-x-auto">
                {sections.map((section) => (
                    <LemonButton
                        key={section.key}
                        size="small"
                        fullWidth
                        active={section.key === active.key}
                        onClick={() => setSetupSection(section.key)}
                        sideIcon={<SectionBadge suggestions={visibleSuggestions} section={section.key} />}
                    >
                        {section.label}
                    </LemonButton>
                ))}
            </nav>

            <div className="grow min-w-0 deprecated-space-y-4">
                <div>
                    <h2 className="mb-1">{active.label}</h2>
                    {active.description && <p className="text-secondary mb-0">{active.description}</p>}
                </div>
                {/* Skipped for "Suggested setup", which renders the whole ranked list
                    itself and would otherwise show everything twice. */}
                {active.key !== SetupSection.SUGGESTIONS && <SectionSuggestions section={active.key} />}
                {active.content}
            </div>

            {/* At the tab, not in a section: a row anywhere can open either, and they
                must survive the user switching sections behind them. */}
            <SuggestionModal
                suggestion={reviewingSuggestion}
                batch={isReviewingBatch ? safeBatch : []}
                isApplying={
                    isReviewingBatch
                        ? safeBatch.some((item) => applyingIds.includes(item.id))
                        : !!reviewingSuggestion && applyingIds.includes(reviewingSuggestion.id)
                }
                onClose={() => reviewSuggestion(null)}
                onConfirm={(item) => {
                    // Navigate ops finish here; everything else goes to the server.
                    if (item.apply && runNavigateOp(item.apply)) {
                        reviewSuggestion(null)
                        return
                    }
                    confirmReviewedSuggestion(item)
                }}
                onConfirmBatch={confirmReviewedBatch}
            />
            {/* UtmAuditTab renders this same modal off the same shared state, so the
                Integration health section would mount two copies of it. */}
            {integrationSettingsModal.integration && active.key !== SetupSection.INTEGRATION_HEALTH && (
                <IntegrationSettingsModal
                    integrationName={integrationSettingsModal.integration}
                    isOpen={integrationSettingsModal.isOpen}
                    onClose={closeIntegrationSettingsModal}
                    initialTab={integrationSettingsModal.initialTab}
                    initialUtmValue={integrationSettingsModal.initialUtmValue}
                    initialCampaignName={integrationSettingsModal.initialCampaignName}
                />
            )}
        </div>
    )
}
