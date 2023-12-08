import { useValues } from 'kea'
import { RefObject } from 'react'

import { groupToName } from './constants'
import { searchBarLogic } from './searchBarLogic'
import { SearchBarTab } from './SearchBarTab'

type SearchTabsProps = {
    inputRef: RefObject<HTMLInputElement>
}

export const SearchTabs = ({ inputRef }: SearchTabsProps): JSX.Element | null => {
    const { tabsGrouped } = useValues(searchBarLogic)
    return (
        <div className="flex flex-col border-r bg-bg-light w-50 grow-0 shrink-0">
            {Object.entries(tabsGrouped).map(([group, tabs]) => (
                <div key={group} className={group !== 'all' ? 'pt-1.5' : ''}>
                    {group !== 'all' && (
                        <span className="ml-4 text-xxs text-muted uppercase">{groupToName[group]}</span>
                    )}
                    {tabs.map((tab) => (
                        <SearchBarTab key={tab} tab={tab} inputRef={inputRef} />
                    ))}
                </div>
            ))}
        </div>
    )
}
