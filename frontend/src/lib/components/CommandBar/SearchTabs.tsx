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
        <div className="flex flex-col border-r bg-bg-light w-50 grow-0 shrink-0">
            {tabs.map((tab) => (
                <SearchBarTab key={tab} tab={tab} inputRef={inputRef} />
            ))}
        </div>
    )
}
