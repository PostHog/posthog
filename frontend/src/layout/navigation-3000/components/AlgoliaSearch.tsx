import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import algoliasearch from 'algoliasearch/lite'
import { useActions } from 'kea'
import { useEffect, useState } from 'react'
import { InstantSearch, useHits, useSearchBox } from 'react-instantsearch'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { List } from 'react-virtualized/dist/es/List'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

const searchClient = algoliasearch('7VNQB5W0TX', '37f41fd37095bc85af76ed4edc85eb5a')

const rowRenderer = ({ key, index, style, hits, activeOption }: any): JSX.Element => {
    const { slug, title } = hits[index]
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <li key={key} style={style} role="listitem" tabIndex={-1} className="p-1 border-b last:border-b-0">
            <LemonButton
                active={activeOption === index}
                to={`https://posthog.com/${slug}`}
                className="[&_>span>span]:flex-col [&_>span>span]:items-start [&_>span>span]:space-y-1"
            >
                <span>
                    <p className="m-0 font-bold font-sans line-clamp-1">{title}</p>
                    <p className="text-xs m-0 opacity-80 font-normal font-sans line-clamp-1">/{slug}</p>
                </span>
            </LemonButton>
        </li>
    )
}

const Hits = ({ activeOption }: { activeOption?: number }): JSX.Element => {
    const { hits } = useHits()
    return (
        <div className="relative flex">
            <ol
                role="listbox"
                className="list-none m-0 p-0 absolute w-full bg-white z-50 border rounded-lg mt-0.5 flex-grow h-[85vh] shadow-xl"
            >
                <AutoSizer>
                    {({ height, width }: { height: number; width: number }) => (
                        <List
                            scrollToIndex={activeOption}
                            width={width}
                            height={height}
                            rowCount={hits.length}
                            rowHeight={50}
                            rowRenderer={(options: any) => rowRenderer({ ...options, hits, activeOption })}
                        />
                    )}
                </AutoSizer>
            </ol>
        </div>
    )
}

const Search = ({
    value,
    setValue,
    setActiveOption,
    activeOption,
}: {
    value: string
    setValue: React.Dispatch<React.SetStateAction<string>>
    setActiveOption: React.Dispatch<React.SetStateAction<number | undefined>>
    activeOption?: number
}): JSX.Element => {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { hits } = useHits()
    const { refine } = useSearchBox()

    const handleChange = (value: string): void => {
        setValue(value)
        refine(value)
    }

    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>): void => {
        switch (e.key) {
            case 'Enter':
                if (activeOption !== undefined) {
                    openSidePanel(SidePanelTab.Docs, `https://posthog.com/${hits[activeOption].slug}`)
                }
                break
            case 'Escape':
                setActiveOption(undefined)
                break
            case 'ArrowDown':
                setActiveOption((currOption) => {
                    if (currOption === undefined) {
                        return 0
                    }
                    if (currOption >= hits.length - 1) {
                        return currOption
                    }
                    return currOption + 1
                })
                break
            case 'ArrowUp':
                setActiveOption((currOption) => {
                    if (currOption !== undefined) {
                        return currOption <= 0 ? undefined : currOption - 1
                    }
                })
        }
    }

    const handleBlur = (): void => {
        setActiveOption(undefined)
    }

    return (
        <LemonInput
            onBlur={handleBlur}
            onKeyDown={handleKeyDown}
            onChange={handleChange}
            value={value}
            type="search"
            fullWidth
            placeholder="Search..."
        />
    )
}

export default function AlgoliaSearch(): JSX.Element {
    const [searchValue, setSearchValue] = useState<string>('')
    const [activeOption, setActiveOption] = useState<undefined | number>()
    const [searchOpen, setSearchOpen] = useState(false)

    useEffect(() => {
        setSearchOpen(!!searchValue)
    }, [searchValue])

    useEffect(() => {
        setSearchOpen(!!searchValue && activeOption !== undefined && activeOption >= -1)
    }, [activeOption])

    return (
        <InstantSearch searchClient={searchClient} indexName="prod_posthog_com">
            <Search
                activeOption={activeOption}
                setActiveOption={setActiveOption}
                value={searchValue}
                setValue={setSearchValue}
            />
            {searchOpen && <Hits activeOption={activeOption} />}
        </InstantSearch>
    )
}
