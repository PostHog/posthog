import { useMountedLogic } from 'kea'
import { useRef } from 'react'

import { searchBarLogic } from './searchBarLogic'
import { SearchInput } from './SearchInput'
import { SearchResults } from './SearchResults'
import { SearchTabs } from './SearchTabs'

export const SearchBar = (): JSX.Element => {
    useMountedLogic(searchBarLogic) // load initial results

    /** Ref to the search input for focusing after tab change. */
    const inputRef = useRef<HTMLInputElement>(null)

    return (
        <div className="grid grid-cols-[8.5rem_1fr] lg:grid-cols-[12.5rem_1fr] w-full h-full">
            <SearchTabs inputRef={inputRef} />
            <div className="grid grid-rows-[auto_100%] overscroll-contain overflow-hidden">
                <SearchInput ref={inputRef} />
                <SearchResults />
            </div>
        </div>
    )
}
