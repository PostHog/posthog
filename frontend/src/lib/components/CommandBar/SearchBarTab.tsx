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
            className={`SearchBarTab flex cursor-pointer items-center whitespace-nowrap border-l-2 px-4 py-2 text-xs ${
                isActive ? 'SearchBarTab__active border-accent font-bold' : 'border-transparent'
            } ${tab === Tab.All ? 'h-9' : ''}`}
            onClick={() => {
                setActiveTab(tab)
                inputRef.current?.focus()
            }}
        >
            {tabToName[tab] || `${capitalizeFirstLetter(aggregationLabel(Number(tab.split('_')[1])).plural)}`}
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
        return <span className="text-xxs text-tertiary ml-1">{tabsCount[tab]}</span>
    }
    return null
}
