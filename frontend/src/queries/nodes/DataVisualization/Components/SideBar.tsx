import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

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
        // The builder's wells own axis/series selection, so the Series tab is redundant for cartesian
        // charts. Keep it for the heatmap (gradient + labels) and the table (per-column formatting),
        // where it's formatting-only with nothing for the wells to conflict with.
        shouldShow: (displayType: ChartDisplayType, isBuilderQuery: boolean): boolean =>
            !isBuilderQuery ||
            displayType === ChartDisplayType.TwoDimensionalHeatmap ||
            displayType === ChartDisplayType.ActionsTable,
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

/** `className` lets callers override the default fixed width (e.g. the builder's Format column fills its shell). */
export const SideBar = ({ className }: { className?: string } = {}): JSX.Element => {
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
        : (tabs[0]?.key as SideBarTab | undefined)

    if (!visibleActiveTab) {
        return (
            <div className={cn('bg-surface-primary w-[18rem] flex flex-col p-4', className)}>
                <span className="text-sm text-secondary">No format options for this chart type.</span>
            </div>
        )
    }

    return (
        <div className={cn('bg-surface-primary w-[18rem] flex flex-col', className)}>
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
