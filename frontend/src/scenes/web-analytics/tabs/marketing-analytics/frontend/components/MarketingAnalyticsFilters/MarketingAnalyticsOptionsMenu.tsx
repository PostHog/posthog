import { useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSwitch } from '@posthog/lemon-ui'
import { Button, Separator, Switch, Text } from '@posthog/quill'

import { QuillTestAccountFilterSwitch } from 'lib/components/QuillTestAccountFilterSwitch'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { OrganizationMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const handleEditMetrics = (): void => {
        setOptionsOpen(false)
        openEditor()
    }
    const testAccountDisabledReason = editRestrictionReason ?? (currentTeamLoading ? 'Saving…' : undefined)

    if (todayRailNav) {
        return (
            <div className="flex w-80 max-w-full flex-col gap-4">
                {showMetricEditor && (
                    <Button
                        variant="outline"
                        className="w-full"
                        onClick={handleEditMetrics}
                        data-attr="marketing-configure-metrics"
                    >
                        <IconPencil />
                        Edit top-line metrics
                    </Button>
                )}
                {canToggleConversionGoals && (
                    <div className="flex flex-col gap-2">
                        <Text size="xs" variant="muted" weight="semibold" render={<div className="m-0" />}>
                            Conversions
                        </Text>
                        <Switch
                            size="sm"
                            checked={includeConversionGoals}
                            onCheckedChange={(checked: boolean) => setShowConversionGoals(checked)}
                            data-attr="marketing-ad-performance-conversion-goals"
                        >
                            Include conversion goals
                        </Switch>
                    </div>
                )}
                {showIntegrations && (
                    <div className="flex flex-col gap-2">
                        <Text size="xs" variant="muted" weight="semibold" render={<div className="m-0" />}>
                            Integrations
                        </Text>
                        <IntegrationFilter />
                    </div>
                )}
                {(showMetricEditor || canToggleConversionGoals || showIntegrations) && <Separator />}
                <QuillTestAccountFilterSwitch
                    checked={shouldFilterTestAccounts}
                    onChange={updateFilterTestAccounts}
                    disabledReason={testAccountDisabledReason}
                />
            </div>
        )
    }

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
                    onClick={handleEditMetrics}
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
                disabledReason={testAccountDisabledReason}
            />
        </div>
    )
}
