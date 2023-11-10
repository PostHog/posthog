import { useMountedLogic } from 'kea'

import { searchBarLogic } from './searchBarLogic'

import SearchInput from './SearchInput'
import SearchResults from './SearchResults'
import SearchTabs from './SearchTabs'

const SearchBar = (): JSX.Element => {
    useMountedLogic(searchBarLogic) // load initial results

    return (
        <div className="flex flex-col h-full">
            <SearchInput />
            <SearchResults />
            <SearchTabs />
        </div>
    )
}

export default SearchBar
