import { Search } from 'lib/components/Search/Search'

export function HomepageSearchResults(): JSX.Element {
    return (
        <Search.Results
            className="w-full mx-auto grow min-h-0"
            listClassName="max-w-[614px] mx-auto w-full"
            groupLabelClassName="bg-[var(--scene-layout-background)]"
        />
    )
}
