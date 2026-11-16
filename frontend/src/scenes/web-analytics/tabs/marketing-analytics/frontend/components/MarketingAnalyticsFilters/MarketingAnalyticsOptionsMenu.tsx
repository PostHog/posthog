import { useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSwitch } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { OrganizationMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { overviewMetricsLogic } from 'products/marketing_analytics/frontend/overview/overviewMetricsLogic'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from '../../logic/marketingAnalyticsTilesLogic'
import { IntegrationFilter } from './IntegrationFilter'

export const MarketingAnalyticsOptionsMenu = ({
    showMetricEditor,
    showIntegrations,
}: {
    showMetricEditor: boolean
    showIntegrations: boolean
}): JSX.Element => {
    const { shouldFilterTestAccounts, includeConversionGoals, canToggleConversionGoals } =
        useValues(marketingAnalyticsLogic)
    const { updateFilterTestAccounts, setOptionsOpen, setShowConversionGoals } = useActions(marketingAnalyticsLogic)
    const { openEditor } = useActions(overviewMetricsLogic({ viewKey: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID }))
    const { currentTeamLoading } = useValues(teamLogic)
    // The setting lives on the project, so flipping it changes what everyone sees.
    const editRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    return (
        // Ordered by how often they get touched, so the rarely-changed
        // project setting sits last.
        <div className="flex w-80 max-w-[90vw] flex-col gap-4 p-3">
            {showMetricEditor && (
                <LemonButton
                    type="secondary"
                    size="small"
                    fullWidth
                    icon={<IconPencil />}
                    onClick={() => {
                        setOptionsOpen(false)
                        openEditor()
                    }}
                    data-attr="marketing-configure-metrics"
                >
                    Edit top-line metrics
                </LemonButton>
            )}
            {canToggleConversionGoals && (
                <div>
                    <div className="text-muted mb-2 text-xs font-semibold uppercase">Conversions</div>
                    <LemonSwitch
                        bordered
                        fullWidth
                        label="Include conversion goals"
                        checked={includeConversionGoals}
                        onChange={setShowConversionGoals}
                        // Kept from the old Ad performance tab, so existing click data still matches.
                        data-attr="marketing-ad-performance-conversion-goals"
                    />
                </div>
            )}
            {showIntegrations && (
                <div>
                    <div className="text-muted mb-2 text-xs font-semibold uppercase">Integrations</div>
                    <IntegrationFilter />
                </div>
            )}
            {(showMetricEditor || canToggleConversionGoals || showIntegrations) && <LemonDivider className="my-0" />}
            {/* Only the event side honors this: ad spend comes from the platforms. */}
            <TestAccountFilterSwitch
                fullWidth
                checked={shouldFilterTestAccounts}
                onChange={updateFilterTestAccounts}
                disabledReason={editRestrictionReason ?? (currentTeamLoading ? 'Saving…' : undefined)}
            />
        </div>
    )
}
