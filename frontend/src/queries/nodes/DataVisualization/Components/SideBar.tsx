import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { ChartDisplayType } from '~/types'

import { SideBarTab, dataVisualizationLogic } from '../dataVisualizationLogic'
import { ConditionalFormattingTab } from './ConditionalFormatting/ConditionalFormattingTab'
import { DisplayTab } from './DisplayTab'
import { SeriesTab } from './SeriesTab'

type TabContent = {
    label: string
    content: JSX.Element
    shouldShow: (displayType: ChartDisplayType, isBuilderQuery: boolean) => boolean
}

const TABS_TO_CONTENT: Record<SideBarTab, TabContent> = {
    [SideBarTab.Series]: {
        label: 'Series',
        content: <SeriesTab />,
        // The insight builder's wells own axis/series selection, so the Series tab is redundant there
        shouldShow: (_displayType: ChartDisplayType, isBuilderQuery: boolean): boolean => !isBuilderQuery,
    },
    [SideBarTab.ConditionalFormatting]: {
        label: 'Conditional formatting',
        content: <ConditionalFormattingTab />,
        shouldShow: (displayType: ChartDisplayType): boolean => displayType === ChartDisplayType.ActionsTable,
    },
    [SideBarTab.Display]: {
        label: 'Display',
        content: <DisplayTab />,
        shouldShow: (displayType: ChartDisplayType): boolean =>
            displayType !== ChartDisplayType.ActionsTable &&
            displayType !== ChartDisplayType.BoldNumber &&
            displayType !== ChartDisplayType.TwoDimensionalHeatmap,
    },
}

export const SideBar = (): JSX.Element => {
    const { activeSideBarTab, effectiveVisualizationType, query } = useValues(dataVisualizationLogic)
    const { setSideBarTab } = useActions(dataVisualizationLogic)

    const isBuilderQuery = !!query.builder?.enabled

    const tabs: LemonTab<string>[] = useMemo(
        () =>
            Object.entries(TABS_TO_CONTENT)
                .filter(([_, tab]) => tab.shouldShow(effectiveVisualizationType, isBuilderQuery))
                .map(([key, tab]) => ({
                    label: tab.label,
                    key,
                })),
        [effectiveVisualizationType, isBuilderQuery]
    )

    // The stored tab can be hidden for the current chart/query (e.g. Series for builder insights)
    const visibleActiveTab = tabs.some((tab) => tab.key === activeSideBarTab)
        ? activeSideBarTab
        : ((tabs[0]?.key as SideBarTab | undefined) ?? activeSideBarTab)

    return (
        <div className="bg-surface-primary w-[18rem] flex flex-col">
            <LemonTabs
                size="small"
                activeKey={visibleActiveTab}
                onChange={(tab) => setSideBarTab(tab as SideBarTab)}
                tabs={tabs}
                className="pt-1"
                barClassName="px-3"
            />
            <div className="flex-1 overflow-y-auto">{TABS_TO_CONTENT[visibleActiveTab].content}</div>
        </div>
    )
}
