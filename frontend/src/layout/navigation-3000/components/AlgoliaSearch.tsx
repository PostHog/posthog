import { LemonButton, LemonInput, LemonTag } from '@posthog/lemon-ui'
import algoliasearch from 'algoliasearch/lite'
import { useActions } from 'kea'
import { useEffect, useRef, useState } from 'react'
import { InstantSearch, useHits, useRefinementList, useSearchBox } from 'react-instantsearch'
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
                className="list-none m-0 p-0 absolute w-full bg-white z-50 border rounded-lg mt-0.5 flex-grow h-[75vh] shadow-xl"
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

const SearchInput = ({
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

type Tag = {
    type: string
    label: string
}

const tags: Tag[] = [
    {
        type: 'docs',
        label: 'Docs',
    },
    {
        type: 'question',
        label: 'Questions',
    },
    {
        type: 'tutorial',
        label: 'Tutorials',
    },
]

type SearchTagProps = Tag & {
    active?: boolean
    onClick: (type: string) => void
}

const SearchTag = ({ type, label, active, onClick }: SearchTagProps): JSX.Element => {
    const { refine } = useRefinementList({ attribute: 'type' })
    const handleClick = (e: React.MouseEvent<HTMLButtonElement, MouseEvent>): void => {
        e.stopPropagation()
        onClick(type)
    }

    useEffect(() => {
        refine(type)
    }, [])

    return (
        <button className="p-0 cursor-pointer" onClick={handleClick}>
            <LemonTag size="medium" type={active ? 'primary' : 'option'}>
                {label}
            </LemonTag>
        </button>
    )
}

const Tags = ({
    activeTag,
    setActiveTag,
}: {
    activeTag: string
    setActiveTag: React.Dispatch<React.SetStateAction<string>>
}): JSX.Element => {
    const handleClick = (type: string): void => {
        setActiveTag(type)
    }

    return (
        <ul className="list-none m-0 p-0 flex space-x-1 mt-1 mb-0.5">
            <li>
                <SearchTag label="All" type="all" active={activeTag === 'all'} onClick={handleClick} />
            </li>
            {tags.map((tag) => {
                const { type } = tag
                return (
                    <li key={type}>
                        <SearchTag {...tag} active={activeTag === type} onClick={handleClick} />
                    </li>
                )
            })}
        </ul>
    )
}

const Search = (): JSX.Element => {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { hits } = useHits()
    const { items, refine } = useRefinementList({ attribute: 'type' })

    const ref = useRef<HTMLDivElement>(null)
    const [searchValue, setSearchValue] = useState<string>('')
    const [activeOption, setActiveOption] = useState<undefined | number>()
    const [activeTag, setActiveTag] = useState('all')
    const [searchOpen, setSearchOpen] = useState(false)

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
                e.preventDefault()
                setActiveOption((currOption) => {
                    if (currOption === undefined || currOption >= hits.length - 1) {
                        return 0
                    }
                    return currOption + 1
                })
                break
            case 'ArrowUp':
                e.preventDefault()
                setActiveOption((currOption) => {
                    if (currOption !== undefined) {
                        return currOption <= 0 ? hits.length - 1 : currOption - 1
                    }
                })
        }
    }

    useEffect(() => {
        setSearchOpen(!!searchValue)
    }, [searchValue])

    useEffect(() => {
        setSearchOpen(!!searchValue && activeOption !== undefined && activeOption >= -1)
    }, [activeOption])

    useEffect(() => {
        setActiveOption(0)
        if (activeTag === 'all') {
            const filteredItems = items.filter(({ value }) => tags.some(({ type }) => type === value))
            filteredItems.forEach(({ value, isRefined }) => {
                if (!isRefined) {
                    refine(value)
                }
            })
        } else {
            items.forEach(({ value, isRefined }) => {
                if (isRefined) {
                    refine(value)
                }
            })
            refine(activeTag)
        }
    }, [activeTag])

    useEffect(() => {
        const handleClick = (e: any): void => {
            if (!ref?.current?.contains(e.target)) {
                setSearchOpen(false)
            }
        }

        window.addEventListener('click', handleClick)

        return () => {
            window.removeEventListener('click', handleClick)
        }
    }, [])

    return (
        <div ref={ref} onKeyDown={handleKeyDown}>
            <SearchInput value={searchValue} setValue={setSearchValue} />
            <Tags activeTag={activeTag} setActiveTag={setActiveTag} />
            {searchOpen && <Hits activeOption={activeOption} />}
        </div>
    )
}

export default function AlgoliaSearch(): JSX.Element {
    return (
        <InstantSearch searchClient={searchClient} indexName="prod_posthog_com">
            <Search />
        </InstantSearch>
    )
}
