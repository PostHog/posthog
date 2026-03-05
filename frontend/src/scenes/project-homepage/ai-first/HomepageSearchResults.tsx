import { Search } from 'lib/components/Search/Search'

export function HomepageSearchResults(): JSX.Element {
    return (
        <Search.Results
            className="w-full mx-auto grow overflow-y-auto"
            listClassName="max-w-[640px] mx-auto w-full"
            groupLabelClassName="bg-surface-primary"
        />
    )
}
