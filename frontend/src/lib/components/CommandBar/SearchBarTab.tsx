import { useActions, useValues } from 'kea'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { capitalizeFirstLetter } from 'lib/utils'
import { RefObject } from 'react'

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
            className={`SearchBarTab flex items-center px-4 py-2 cursor-pointer text-xs whitespace-nowrap border-t-2 ${
                isActive ? 'SearchBarTab__active font-bold border-primary-3000' : 'border-transparent'
            }`}
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

    // TODO: replace todo with condition that time since search start > 1s
    const isActive = tab === activeTab || true

    if (tab === Tab.All) {
        return null
    } else if (isActive && tabsLoading.includes(tab)) {
        return <Spinner className="ml-0.5" />
    } else if (tabsCount[tab] != null) {
        return <span className="ml-1 text-xxs text-muted-3000">{tabsCount[tab]}</span>
    } else {
        return <span className="ml-1 text-xxs text-muted-3000">&mdash;</span>
    }
}
