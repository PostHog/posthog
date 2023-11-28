import { RefObject } from 'react'

import { Tab } from './constants'
import { SearchBarTab } from './SearchBarTab'

type SearchTabsProps = {
    inputRef: RefObject<HTMLInputElement>
}

export const SearchTabs = ({ inputRef }: SearchTabsProps): JSX.Element | null => (
    <div className="flex items-center border-t shrink-0 overflow-x-auto bg-bg-light">
        {Object.values(Tab).map((tab) => (
            <SearchBarTab key={tab} tab={tab} inputRef={inputRef} />
        ))}
    </div>
)
