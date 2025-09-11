import { useValues } from 'kea'
import { RefObject } from 'react'

import { SearchBarTab } from './SearchBarTab'
import { groupToName } from './constants'
import { searchBarLogic } from './searchBarLogic'

type SearchTabsProps = {
    inputRef: RefObject<HTMLInputElement>
}

export const SearchTabs = ({ inputRef }: SearchTabsProps): JSX.Element | null => {
    const { tabsGrouped } = useValues(searchBarLogic)
    return (
        <div className="flex flex-col border-r bg-surface-primary overflow-y-auto">
            {Object.entries(tabsGrouped).map(([group, tabs]) => (
                <div key={group} className={group !== 'all' ? 'pt-1.5' : ''}>
                    {group !== 'all' && (
                        <span className="ml-4 text-xxs text-secondary uppercase">
                            {groupToName[group as keyof typeof groupToName]}
                        </span>
                    )}
                    {tabs.map((tab) => (
                        <SearchBarTab key={tab} tab={tab} inputRef={inputRef} />
                    ))}
                </div>
            ))}
        </div>
    )
}
