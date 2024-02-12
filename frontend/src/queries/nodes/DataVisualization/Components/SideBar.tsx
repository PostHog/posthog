import './SideBar.scss'

import { LemonTabs } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { dataVisualizationLogic, SideBarTab } from '../dataVisualizationLogic'
import { DisplayTab } from './DisplayTab'
import { SeriesTab } from './SeriesTab'

const TABS_TO_CONTENT = {
    [SideBarTab.Series]: {
        label: 'Series',
        content: <SeriesTab />,
    },
    [SideBarTab.Display]: {
        label: 'Display',
        content: <DisplayTab />,
    },
}

const ContentWrapper = ({ children }: { children: JSX.Element }): JSX.Element => {
    return <div className="SideBar bg-bg-light border p-4 rounded-t-none border-t-0">{children}</div>
}

export const SideBar = (): JSX.Element => {
    const { activeSideBarTab } = useValues(dataVisualizationLogic)
    const { setSideBarTab } = useActions(dataVisualizationLogic)

    return (
        <LemonTabs
            activeKey={activeSideBarTab}
            onChange={(tab) => setSideBarTab(tab as SideBarTab)}
            tabs={Object.values(TABS_TO_CONTENT).map((tab, index) => ({
                label: tab.label,
                key: Object.keys(TABS_TO_CONTENT)[index],
                content: <ContentWrapper>{tab.content}</ContentWrapper>,
            }))}
        />
    )
}
