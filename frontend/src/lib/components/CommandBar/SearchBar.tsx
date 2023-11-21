import { useMountedLogic } from 'kea'
import { useRef } from 'react'

import { searchBarLogic } from './searchBarLogic'

import { SearchInput } from './SearchInput'
import { SearchResults } from './SearchResults'
import { SearchTabs } from './SearchTabs'

export const SearchBar = (): JSX.Element => {
    useMountedLogic(searchBarLogic) // load initial results

    const inputRef = useRef<HTMLInputElement>(null)

    return (
        <div className="flex flex-col h-full">
            <SearchInput ref={inputRef} />
            <SearchResults />
            <SearchTabs inputRef={inputRef} />
        </div>
    )
}
