import { useValues } from 'kea'

import { searchBarLogic } from './searchBarLogic'
import SearchBarTab from './SearchBarTab'
import { ResultType } from './types'

const SearchTabs = (): JSX.Element | null => {
    const { searchResponse, activeTab } = useValues(searchBarLogic)

    if (!searchResponse) {
        return null
    }

    return (
        <div className="flex items-center border-t space-x-3 px-2">
            <SearchBarTab type="all" active={activeTab === 'all'} />
            {Object.entries(searchResponse.counts).map(([type, count]) => (
                <SearchBarTab key={type} type={type as ResultType} count={count} active={activeTab === type} />
            ))}
        </div>
    )
}
export default SearchTabs
