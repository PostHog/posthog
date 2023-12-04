import { useValues } from 'kea'
import { RefObject } from 'react'

import { searchBarLogic } from './searchBarLogic'
import { SearchBarTab } from './SearchBarTab'

type SearchTabsProps = {
    inputRef: RefObject<HTMLInputElement>
}

export const SearchTabs = ({ inputRef }: SearchTabsProps): JSX.Element | null => {
    const { tabs } = useValues(searchBarLogic)
    return (
        <div className="flex items-center border-t shrink-0 overflow-x-auto bg-bg-light">
            {tabs.map((tab) => (
                <SearchBarTab key={tab} tab={tab} inputRef={inputRef} />
            ))}
        </div>
    )
}
