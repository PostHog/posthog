import './SideBar.scss'

import { LemonTab, LemonTabs } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { ChartDisplayType } from '~/types'

import { dataVisualizationLogic, SideBarTab } from '../dataVisualizationLogic'
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

const ContentWrapper = ({ children }: { children: JSX.Element }): JSX.Element => {
    return <div className="SideBar bg-card border p-4 rounded-t-none">{children}</div>
}

export const SideBar = (): JSX.Element => {
    const { activeSideBarTab, visualizationType } = useValues(dataVisualizationLogic)
    const { setSideBarTab } = useActions(dataVisualizationLogic)

    const tabs: LemonTab<string>[] = Object.values(TABS_TO_CONTENT)
        .filter((n) => n.shouldShow(visualizationType))
        .map((tab, index) => ({
            label: tab.label,
            key: Object.keys(TABS_TO_CONTENT)[index],
            content: <ContentWrapper>{tab.content}</ContentWrapper>,
        }))

    return <LemonTabs activeKey={activeSideBarTab} onChange={(tab) => setSideBarTab(tab as SideBarTab)} tabs={tabs} />
}
