import { useActions, useValues } from 'kea'

import { AlertDeletionWarning } from 'lib/components/Alerts/AlertDeletionWarning'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { insightNavLogic } from 'scenes/insights/InsightNav/insightNavLogic'
import { INSIGHT_TYPE_URLS } from 'scenes/insights/utils'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'

import { insightLogic } from '../insightLogic'
import { FunnelsCue } from '../views/Trends/FunnelsCue'

export function InsightsNav(): JSX.Element {
    const { insightProps, insight } = useValues(insightLogic)
    const { activeView, tabs } = useValues(insightNavLogic(insightProps))
    const { setActiveView } = useActions(insightNavLogic(insightProps))

    return (
        <>
            <FunnelsCue />
            {insight.short_id && <AlertDeletionWarning />}
            <LemonTabs
                activeKey={activeView}
                onChange={(newKey) => setActiveView(newKey)}
                tabs={tabs.map(({ label, type, dataAttr }) => ({
                    key: type,
                    label: (
                        <Link to={INSIGHT_TYPE_URLS[type]} preventClick data-attr={dataAttr}>
                            <Tooltip
                                placement="top"
                                title={
                                    INSIGHT_TYPES_METADATA[type].tooltipDescription ||
                                    INSIGHT_TYPES_METADATA[type].description
                                }
                                docLink={INSIGHT_TYPES_METADATA[type].tooltipDocLink}
                            >
                                <span>{label}</span>
                            </Tooltip>
                        </Link>
                    ),
                }))}
            />
        </>
    )
}
