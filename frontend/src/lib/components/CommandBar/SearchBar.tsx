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
        <div className="flex w-full h-full">
            <SearchTabs inputRef={inputRef} />
            <div className="grow flex flex-col overscroll-contain overflow-hidden">
                <SearchInput ref={inputRef} />
                <SearchResults />
            </div>
        </div>
    )
}
