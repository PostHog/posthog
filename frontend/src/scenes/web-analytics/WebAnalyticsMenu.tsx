import { IconEllipsis, IconSearch } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

export const WebAnalyticsMenu = (): JSX.Element => {
    const { shouldFilterTestAccounts } = useValues(webAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeam } = useValues(teamLogic)

    const { setShouldFilterTestAccounts } = useActions(webAnalyticsLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    const handlePreAggChange = (mode: boolean): void => {
        updateCurrentTeam({ modifiers: { ...currentTeam?.modifiers, useWebAnalyticsPreAggregatedTables: mode } })
    }

    return (
        <LemonMenu
            items={[
                {
                    label: 'Session Attribution Explorer',
                    to: urls.sessionAttributionExplorer(),
                    icon: <IconSearch />,
                },
                {
                    label: () => (
                        <LemonSwitch
                            checked={shouldFilterTestAccounts}
                            onChange={() => {
                                setShouldFilterTestAccounts(!shouldFilterTestAccounts)
                            }}
                            fullWidth={true}
                            label="Filter test accounts"
                        />
                    ),
                },
                featureFlags[FEATURE_FLAGS.SETTINGS_WEB_ANALYTICS_PRE_AGGREGATED_TABLES]
                    ? {
                          label: () => (
                              <LemonSwitch
                                  checked={currentTeam?.modifiers?.useWebAnalyticsPreAggregatedTables ?? false}
                                  onChange={handlePreAggChange}
                                  fullWidth={true}
                                  label="Allow pre-aggregated tables"
                              />
                          ),
                      }
                    : null,
            ].filter(Boolean)}
            closeOnClickInside={false}
        >
            <LemonButton icon={<IconEllipsis />} size="small" />
        </LemonMenu>
    )
}
