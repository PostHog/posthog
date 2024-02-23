import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import algoliasearch from 'algoliasearch/lite'
import { Key, useState } from 'react'
import { InstantSearch, useHits, useSearchBox } from 'react-instantsearch'

const searchClient = algoliasearch('7VNQB5W0TX', '37f41fd37095bc85af76ed4edc85eb5a')

const Hits = (): JSX.Element => {
    const { hits } = useHits()

    return (
        <div className="relative">
            <ol className="list-none m-0 p-0 absolute w-full bg-white z-50 border rounded-sm max-h-[85vh] overflow-auto mt-0.5 divide-y shadow-xl">
                {hits.map(({ title, excerpt, slug, id }) => {
                    return (
                        <li className="p-1" key={id as Key}>
                            <LemonButton
                                to={`https://posthog.com/${slug}`}
                                className="[&_>span>span]:flex-col [&_>span>span]:items-start [&_>span>span]:space-y-1"
                            >
                                <p className="m-0 font-bold font-sans">{title}</p>
                                <p className="text-xs m-0 opacity-80 font-normal font-sans">{excerpt}</p>
                            </LemonButton>
                        </li>
                    )
                })}
            </ol>
        </div>
    )
}

const Search = ({
    value,
    setValue,
}: {
    value: string
    setValue: React.Dispatch<React.SetStateAction<string>>
}): JSX.Element => {
    const { refine } = useSearchBox()

    const handleChange = (value: string): void => {
        setValue(value)
        refine(value)
    }

    return <LemonInput onChange={handleChange} value={value} type="search" fullWidth placeholder="Search..." />
}

export default function AlgoliaSearch(): JSX.Element {
    const [searchValue, setSearchValue] = useState<string>('')

    return (
        <InstantSearch searchClient={searchClient} indexName="prod_posthog_com">
            <Search value={searchValue} setValue={setSearchValue} />
            {searchValue && <Hits />}
        </InstantSearch>
    )
}
