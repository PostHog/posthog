import { useActions, useValues } from 'kea'
import { RefObject } from 'react'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { capitalizeFirstLetter } from 'lib/utils'

import { Tab, tabToName } from './constants'
import { searchBarLogic } from './searchBarLogic'

type SearchBarTabProps = {
    tab: Tab
    inputRef: RefObject<HTMLInputElement>
}

export const SearchBarTab = ({ tab, inputRef }: SearchBarTabProps): JSX.Element => {
    const { activeTab, aggregationLabel } = useValues(searchBarLogic)
    const { setActiveTab } = useActions(searchBarLogic)

    const isActive = tab === activeTab

    return (
        <div
            className={`SearchBarTab flex items-center px-4 py-2 cursor-pointer text-xs whitespace-nowrap border-l-2 ${
                isActive ? 'SearchBarTab__active font-bold border-accent' : 'border-transparent'
            } ${tab === Tab.All ? 'h-9' : ''}`}
            onClick={() => {
                setActiveTab(tab)
                inputRef.current?.focus()
            }}
        >
            <span className="truncate">
                {tabToName[tab] || `${capitalizeFirstLetter(aggregationLabel(Number(tab.split('_')[1])).plural)}`}
            </span>
            <Count tab={tab} />
        </div>
    )
}

type CountProps = {
    tab: Tab
}

const Count = ({ tab }: CountProps): JSX.Element | null => {
    const { activeTab, tabsCount, tabsLoading } = useValues(searchBarLogic)

    const isLoading = tabsLoading.length > 0

    if (isLoading && tab === Tab.All && activeTab === Tab.All) {
        return <Spinner className="ml-0.5" />
    } else if (tabsLoading.includes(tab) && activeTab !== Tab.All) {
        return <Spinner className="ml-0.5" />
    } else if (!isLoading && tabsCount[tab] != null) {
        return <span className="ml-1 text-xxs text-tertiary">{tabsCount[tab]}</span>
    }
    return null
}
