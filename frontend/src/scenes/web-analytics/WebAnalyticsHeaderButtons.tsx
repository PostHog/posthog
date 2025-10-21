import { useActions, useValues } from 'kea'

import { IconBolt, IconInfo } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { WebAnalyticsMenu } from 'scenes/web-analytics/WebAnalyticsMenu'

export function WebAnalyticsHeaderButtons(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    const hasFeatureFlag = featureFlags[FEATURE_FLAGS.SETTINGS_WEB_ANALYTICS_PRE_AGGREGATED_TABLES]
    const isUsingNewEngine = currentTeam?.modifiers?.useWebAnalyticsPreAggregatedTables

    const handleToggleEngine = (checked: boolean): void => {
        updateCurrentTeam({
            modifiers: {
                ...currentTeam?.modifiers,
                useWebAnalyticsPreAggregatedTables: checked,
            },
        })
    }

    return (
        <div className="flex items-center gap-2">
            {hasFeatureFlag && (
                <Tooltip
                    title={
                        <>
                            <strong>New query engine (Beta)</strong>
                            <div className="mt-1">
                                Faster queries using pre-aggregated data. Some filters may not yet be supported.{' '}
                                <Link
                                    to={urls.settings(
                                        'environment-web-analytics',
                                        'web-analytics-pre-aggregated-tables'
                                    )}
                                >
                                    Learn more
                                </Link>
                            </div>
                        </>
                    }
                >
                    <div className="flex items-center gap-2">
                        <IconInfo className="text-muted" />
                        <IconBolt className={isUsingNewEngine ? 'text-warning' : 'text-muted'} />
                        <span className="text-sm font-medium">Use new query engine</span>
                        <LemonSwitch checked={!!isUsingNewEngine} onChange={handleToggleEngine} size="small" />
                    </div>
                </Tooltip>
            )}
            <WebAnalyticsMenu />
        </div>
    )
}
