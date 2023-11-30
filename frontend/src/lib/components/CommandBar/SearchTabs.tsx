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
        <div className="flex flex-col flex-wrap min-w-60 bg-bg-light border-r">
            {tabs.map((tab) => (
                <SearchBarTab key={tab} tab={tab} inputRef={inputRef} />
            ))}
        </div>
    )
}
