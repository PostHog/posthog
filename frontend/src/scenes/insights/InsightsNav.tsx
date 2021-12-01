import { Tabs } from 'antd'
import { useActions, useValues } from 'kea'
import { isMobile } from 'lib/utils'
import React, { ReactNode, RefObject, useMemo, useRef } from 'react'
import { HotKeys, InsightType } from '~/types'
import { insightLogic } from './insightLogic'
import { Tooltip } from 'lib/components/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import clsx from 'clsx'
import { FunnelsCue } from './InsightTabs/TrendTab/FunnelsCue'
import { Link } from 'lib/components/Link'

const { TabPane } = Tabs

function InsightHotkey({ hotkey }: { hotkey: HotKeys }): JSX.Element {
    return !isMobile() ? <span className="hotkey">{hotkey}</span> : <></>
}

interface Tab {
    label: string
    type: InsightType
    dataAttr: string
    hotkey: HotKeys
    tooltip?: ReactNode
    ref?: RefObject<HTMLSpanElement>
    className?: string
}

export function InsightsNav(): JSX.Element {
    const { activeView, insightProps, createInsightUrl } = useValues(insightLogic)
    const { setActiveView } = useActions(insightLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const funnelTab = useRef<HTMLSpanElement>(null)

    const tabs: Tab[] = useMemo(
        () => [
            {
                label: 'Trends',
                type: InsightType.TRENDS,
                dataAttr: 'insight-trends-tab',
                hotkey: 't',
            },
            {
                label: 'Funnels',
                type: InsightType.FUNNELS,
                dataAttr: 'insight-funnels-tab',
                hotkey: 'f',
                ref: funnelTab,
            },
            {
                label: 'Retention',
                type: InsightType.RETENTION,
                dataAttr: 'insight-retention-tab',
                hotkey: 'r',
            },
            {
                label: 'User Paths',
                type: InsightType.PATHS,
                dataAttr: 'insight-path-tab',
                hotkey: 'p',
            },
            {
                label: 'Stickiness',
                type: InsightType.STICKINESS,
                dataAttr: 'insight-stickiness-tab',
                hotkey: 'i',
                tooltip: (
                    <>
                        Stickiness shows you how many days users performed an action repeatedly within a timeframe.
                        <br />
                        <br />
                        <i>
                            Example: If a user performed an action on Monday and again on Friday, it would be shown as
                            "2 days".
                        </i>
                    </>
                ),
            },
            {
                label: 'Lifecycle',
                type: InsightType.LIFECYCLE,
                dataAttr: 'insight-lifecycle-tab',
                hotkey: 'i',
                tooltip: 'Understand growth by breaking down new, resurrected, returning, and dormant users.',
            },
            {
                label: 'Sessions',
                type: InsightType.SESSIONS,
                dataAttr: 'insight-sessions-tab',
                hotkey: 'o',
                tooltip: 'View average and distribution of session durations.',
                className: clsx(featureFlags[FEATURE_FLAGS.SESSION_INSIGHT_REMOVAL] && 'deprecated'),
            },
        ],
        [funnelTab]
    )

    return (
        <>
            <FunnelsCue
                props={insightProps}
                tooltipPosition={
                    // 1.5x because it's 2 tabs (trends & funnels) + margin between tabs
                    funnelTab?.current ? funnelTab.current.getBoundingClientRect().width * 1.5 + 16 : undefined
                }
            />
            <Tabs
                activeKey={activeView}
                className="top-bar"
                onChange={(key) => setActiveView(key as InsightType)}
                animated={false}
            >
                {tabs.map(({ label, type, dataAttr, hotkey, tooltip, ref, className }) => {
                    const Outer = ({ children }: { children: ReactNode }): JSX.Element =>
                        tooltip ? (
                            <Tooltip placement="top" title={tooltip} data-attr={dataAttr}>
                                {children}
                            </Tooltip>
                        ) : (
                            <span data-attr={dataAttr} ref={ref}>
                                {children}
                            </span>
                        )
                    return (
                        <TabPane
                            key={type}
                            tab={
                                <Link className={clsx('tab-text', className)} to={createInsightUrl(type)}>
                                    <Outer>
                                        {label}
                                        <InsightHotkey hotkey={hotkey} />
                                    </Outer>
                                </Link>
                            }
                        />
                    )
                })}
            </Tabs>
        </>
    )
}
