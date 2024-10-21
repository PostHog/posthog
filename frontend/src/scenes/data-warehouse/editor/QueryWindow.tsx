import { useValues, useActions } from 'kea'
import { QueryPane } from './QueryPane'
import { QueryTabs } from './QueryTabs'
import { ResultPane } from './ResultPane'
import { queryWindowLogic } from './queryWindowLogic'

export function QueryWindow(): JSX.Element {
    const { tabs, activeTabKey } = useValues(queryWindowLogic)
    const { selectTab, addTab, deleteTab } = useActions(queryWindowLogic)

    return (
        <div className="flex flex-1 flex-col h-full">
            <QueryTabs
                tabs={tabs}
                onTabClick={(tab) => selectTab(tab)}
                onTabClear={(tab) => deleteTab(tab)}
                onAdd={() => addTab()}
                activeKey={activeTabKey}
            />
            <QueryPane />
            <ResultPane />
        </div>
    )
}
