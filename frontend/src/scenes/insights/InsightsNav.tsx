import { Tabs } from 'antd'
import { useActions, useValues } from 'kea'
import { InsightType } from '~/types'
import { insightLogic } from './insightLogic'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { FunnelsCue } from './views/Trends/FunnelsCue'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

interface Tab {
    label: string
    type: InsightType
    dataAttr: string
}

export function InsightsNav(): JSX.Element {
    const { activeView } = useValues(insightLogic)
    const { setActiveView } = useActions(insightLogic)

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
        {
            label: 'Query',
            type: InsightType.QUERY,
            dataAttr: 'insight-query-tab',
        },
    ]

    return (
        <>
            <FunnelsCue />
            <Tabs
                activeKey={activeView}
                className="top-bar"
                onChange={(key) => setActiveView(key as InsightType)}
                animated={false}
            >
                {tabs.map(({ label, type, dataAttr }) => (
                    <Tabs.TabPane
                        key={type}
                        tab={
                            <Link
                                className="tab-text"
                                to={urls.insightNew({ insight: type })}
                                preventClick
                                data-attr={dataAttr}
                            >
                                <Tooltip placement="top" title={INSIGHT_TYPES_METADATA[type].description}>
                                    {label}
                                </Tooltip>
                            </Link>
                        }
                    />
                ))}
            </Tabs>
        </>
    )
}
