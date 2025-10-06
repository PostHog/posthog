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
    shouldShow: (displayType: ChartDisplayType) => boolean
}

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
        shouldShow: (displayType: ChartDisplayType): boolean =>
            displayType !== ChartDisplayType.ActionsTable && displayType !== ChartDisplayType.BoldNumber,
    },
}

export const SideBar = (): JSX.Element => {
    const { activeSideBarTab, visualizationType } = useValues(dataVisualizationLogic)
    const { setSideBarTab } = useActions(dataVisualizationLogic)

    const tabs: LemonTab<string>[] = useMemo(
        () =>
            Object.entries(TABS_TO_CONTENT)
                .filter(([_, tab]) => tab.shouldShow(visualizationType))
                .map(([key, tab]) => ({
                    label: tab.label,
                    key,
                })),
        [visualizationType]
    )

    return (
        <div className="bg-surface-primary w-[18rem] flex flex-col">
            <LemonTabs
                size="small"
                activeKey={activeSideBarTab}
                onChange={(tab) => setSideBarTab(tab as SideBarTab)}
                tabs={tabs}
                className="pt-1"
                barClassName="px-3"
            />
            <div className="flex-1 overflow-y-auto">{TABS_TO_CONTENT[activeSideBarTab].content}</div>
        </div>
    )
}
