import { Tabs } from 'antd'
import { useActions, useValues } from 'kea'
import { RefObject, useEffect, useState, useRef } from 'react'
import { InsightType } from '~/types'
import { insightLogic } from './insightLogic'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { FunnelsCue } from './views/Trends/FunnelsCue'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

const { TabPane } = Tabs

interface Tab {
    label: string
    type: InsightType
    dataAttr: string
    ref?: RefObject<HTMLSpanElement>
}

export function InsightsNav(): JSX.Element {
    const { activeView, filters } = useValues(insightLogic)
    const { setActiveView } = useActions(insightLogic)
    const trendsTab = useRef<HTMLSpanElement>(null)
    const funnelTab = useRef<HTMLSpanElement>(null)
    const [tooltipPosition, setTooltipPosition] = useState<number | undefined>()

    const tabs: Tab[] = [
        {
            label: 'Trends',
            type: InsightType.TRENDS,
            dataAttr: 'insight-trends-tab',
            ref: trendsTab,
        },
        {
            label: 'Funnels',
            type: InsightType.FUNNELS,
            dataAttr: 'insight-funnels-tab',
            ref: funnelTab,
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

    useEffect(() => {
        if (trendsTab.current && funnelTab.current) {
            const f = funnelTab.current.getBoundingClientRect()
            const t = trendsTab.current.getBoundingClientRect()
            const arrowWidth = 10
            const offset = f.x - t.x + f.width / 2 - arrowWidth / 2
            setTooltipPosition(offset)
        }
    }, [trendsTab.current, funnelTab.current])

    return (
        <>
            <FunnelsCue tooltipPosition={tooltipPosition} />
            <Tabs
                activeKey={activeView}
                className="top-bar"
                onChange={(key) => setActiveView(key as InsightType)}
                animated={false}
            >
                {tabs.map(({ label, type, dataAttr, ref }) => (
                    <TabPane
                        key={type}
                        tab={
                            <Link
                                className="tab-text"
                                to={urls.insightNew({ ...filters, insight: type })}
                                preventClick
                                data-attr={dataAttr}
                            >
                                <span ref={ref}>
                                    <Tooltip placement="top" title={INSIGHT_TYPES_METADATA[type].description}>
                                        {label}
                                    </Tooltip>
                                </span>
                            </Link>
                        }
                    />
                ))}
            </Tabs>
        </>
    )
}
