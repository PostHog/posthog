import { useValues } from 'kea'

import { actionBarLogic } from './actionBarLogic'
import SearchBarTab from './SearchBarTab'
import { ResultType } from './types'

const ActionTabs = (): JSX.Element | null => {
    const { commandSearchResultsGrouped, commandSearchResults, activeFlow } = useValues(actionBarLogic)

    console.debug('commandSearchResults', commandSearchResults)
    console.debug('commandSearchResultsGrouped', commandSearchResultsGrouped)
    console.debug('activeFlow', activeFlow)

    return (
        <div className="flex items-center border-t space-x-3 px-2">
            {/* <SearchBarTab type="all" active={activeTab === 'all'} />
            {Object.entries(searchResponse.counts).map(([type, count]) => (
                <SearchBarTab key={type} type={type as ResultType} count={count} active={activeTab === type} />
            ))} */}
        </div>
    )
}
export default ActionTabs
