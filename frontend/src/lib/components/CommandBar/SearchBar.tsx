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
        <div className="flex h-full">
            <SearchTabs inputRef={inputRef} />
            <div className="w-full">
                <SearchInput ref={inputRef} />
                <SearchResults />
            </div>
        </div>
    )
}
