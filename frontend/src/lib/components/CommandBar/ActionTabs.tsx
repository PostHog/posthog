import { useValues } from 'kea'

import { actionBarLogic } from './actionBarLogic'
import SearchBarTab from './SearchBarTab'
import { ResultType } from './types'

const ActionTabs = (): JSX.Element | null => {
    const { commandSearchResultsGrouped, activeTab } = useValues(actionBarLogic)

    console.debug('commandSearchResultsGrouped', commandSearchResultsGrouped)

    return (
        <div className="flex items-center border-t">
            {/* <SearchBarTab type="all" isFirst active={activeTab === 'all'} />
            {Object.entries(searchResponse.counts).map(([type, count]) => (
                <SearchBarTab key={type} type={type as ResultType} count={count} active={activeTab === type} />
            ))} */}
        </div>
    )
}
export default ActionTabs
