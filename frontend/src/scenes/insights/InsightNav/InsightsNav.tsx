import { useActions, useValues } from 'kea'
import { InsightType } from '~/types'
import { insightLogic } from '../insightLogic'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { FunnelsCue } from '../views/Trends/FunnelsCue'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { insightNavLogic } from 'scenes/insights/InsightNav/insightNavLogic'

interface Tab {
    label: string
    type: InsightType
    dataAttr: string
}

export function InsightsNav(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { activeView } = useValues(insightNavLogic(insightProps))
    const { setActiveView } = useActions(insightNavLogic(insightProps))

    const tabs: Tab[] = [
        {
            label: 'Trends',
            type: InsightType.TRENDS,
            dataAttr: 'insight-trends-tab',
        },
        {
            label: 'Funnels',
            type: InsightType.FUNNELS,
            dataAttr: 'insight-funnels-tab',
        },
        {
            label: 'Retention',
            type: InsightType.RETENTION,
            dataAttr: 'insight-retention-tab',
        },
        {
            label: 'User Paths',
            type: InsightType.PATHS,
            dataAttr: 'insight-path-tab',
        },
        {
            label: 'Stickiness',
            type: InsightType.STICKINESS,
            dataAttr: 'insight-stickiness-tab',
        },
        {
            label: 'Lifecycle',
            type: InsightType.LIFECYCLE,
            dataAttr: 'insight-lifecycle-tab',
        },
    ]

    return (
        <>
            <FunnelsCue />
            <LemonTabs
                activeKey={activeView}
                onChange={(newKey) => setActiveView(newKey)}
                tabs={tabs.map(({ label, type, dataAttr }) => ({
                    key: type,
                    label: (
                        <Link to={urls.insightNew({ insight: type })} preventClick data-attr={dataAttr}>
                            <Tooltip placement="top" title={INSIGHT_TYPES_METADATA[type].description}>
                                {label}
                            </Tooltip>
                        </Link>
                    ),
                }))}
            />
        </>
    )
}
