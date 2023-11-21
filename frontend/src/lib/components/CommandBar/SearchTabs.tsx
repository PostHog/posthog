import { useValues } from 'kea'
import { RefObject } from 'react'

import { searchBarLogic } from './searchBarLogic'
import { SearchBarTab } from './SearchBarTab'
import { ResultType } from './types'

type SearchTabsProps = {
    inputRef: RefObject<HTMLInputElement>
}

export const SearchTabs = ({ inputRef }: SearchTabsProps): JSX.Element | null => {
    const { searchResponse, activeTab } = useValues(searchBarLogic)

    if (!searchResponse) {
        return null
    }

    return (
        <div className="flex items-center border-t shrink-0 overflow-x-auto bg-bg-light">
            <SearchBarTab type="all" active={activeTab === 'all'} inputRef={inputRef} />
            {Object.entries(searchResponse.counts).map(([type, count]) => (
                <SearchBarTab
                    key={type}
                    type={type as ResultType}
                    count={count}
                    active={activeTab === type}
                    inputRef={inputRef}
                />
            ))}
        </div>
    )
}
