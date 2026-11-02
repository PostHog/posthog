import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { isBIPivotTable } from 'products/business_intelligence/frontend/biTableLayout'

import { SideBarTab, dataVisualizationLogic } from '../dataVisualizationLogic'
import { ConditionalFormattingTab } from './ConditionalFormatting/ConditionalFormattingTab'
import { DisplayTab } from './DisplayTab'
import { SeriesTab } from './SeriesTab'

type TabContent = {
    label: string
    content: JSX.Element
    shouldShow: (displayType: ChartDisplayType) => boolean
}

export const isDisplayTabSupported = (displayType: ChartDisplayType): boolean =>
    displayType !== ChartDisplayType.ActionsTable &&
    displayType !== ChartDisplayType.BoldNumber &&
    displayType !== ChartDisplayType.TwoDimensionalHeatmap

const TABS_TO_CONTENT: Record<SideBarTab, TabContent> = {
    [SideBarTab.Series]: {
        label: 'Series',
        content: <SeriesTab />,
        shouldShow: (): boolean => true,
    },
    [SideBarTab.ConditionalFormatting]: {
        label: 'Conditional formatting',
        content: <ConditionalFormattingTab />,
        shouldShow: (displayType: ChartDisplayType): boolean => displayType === ChartDisplayType.ActionsTable,
    },
    [SideBarTab.Display]: {
        label: 'Display',
        content: <DisplayTab />,
        shouldShow: isDisplayTabSupported,
    },
}

export const SideBar = ({ className = 'w-72 max-w-[50%] shrink-0' }: { className?: string }): JSX.Element => {
    const { activeSideBarTab, effectiveVisualizationType, query } = useValues(dataVisualizationLogic)
    const { setSideBarTab } = useActions(dataVisualizationLogic)

    const isPivot = query.kind === NodeKind.BIVisualizationNode && isBIPivotTable(query.config)
    const tabs: LemonTab<string>[] = useMemo(
        () =>
            Object.entries(TABS_TO_CONTENT)
                .filter(
                    ([key, tab]) =>
                        tab.shouldShow(effectiveVisualizationType) ||
                        (key === SideBarTab.ConditionalFormatting && isPivot)
                )
                .map(([key, tab]) => ({
                    label: tab.label,
                    key,
                })),
        [effectiveVisualizationType, isPivot]
    )

    const activeTab = tabs.some((tab) => tab.key === activeSideBarTab) ? activeSideBarTab : SideBarTab.Series

    return (
        <div className={`bg-surface-primary min-h-0 flex flex-col ${className}`}>
            <LemonTabs
                size="small"
                activeKey={activeTab}
                onChange={(tab) => setSideBarTab(tab as SideBarTab)}
                tabs={tabs}
                className="pt-1"
                barClassName="px-3"
            />
            <div className="min-h-0 flex-1 overflow-y-auto">{TABS_TO_CONTENT[activeTab].content}</div>
        </div>
    )
}
