import { useMountedLogic } from 'kea'
import { useRef } from 'react'

import { SearchInput } from './SearchInput'
import { SearchResults } from './SearchResults'
import { SearchTabs } from './SearchTabs'
import { searchBarLogic } from './searchBarLogic'

export const SearchBar = (): JSX.Element => {
    useMountedLogic(searchBarLogic) // load initial results

    /** Ref to the search input for focusing after tab change. */
    const inputRef = useRef<HTMLInputElement>(null)

    return (
        <div className="grid grid-cols-[8.5rem_1fr] lg:grid-cols-[12.5rem_1fr] h-full">
            <SearchTabs inputRef={inputRef} />
            {/* 49px = height of search input, 40rem = height of search results */}
            <div className="grid grid-rows-[49px_calc(40rem-49px)] overflow-hidden overscroll-contain">
                <SearchInput ref={inputRef} />
                <SearchResults />
            </div>
        </div>
    )
}
