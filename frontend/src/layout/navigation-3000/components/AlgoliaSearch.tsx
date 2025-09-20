import algoliasearch from 'algoliasearch/lite'
import { useActions } from 'kea'
import { useEffect, useRef, useState } from 'react'
import { InstantSearch, useHits, useRefinementList, useSearchBox } from 'react-instantsearch'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { List } from 'react-virtualized/dist/es/List'

import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTag } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

const searchClient = algoliasearch('7VNQB5W0TX', '37f41fd37095bc85af76ed4edc85eb5a')

const rowRenderer = ({ key, index, style, hits, activeOption }: any): JSX.Element => {
    const { slug, title, type, resolved } = hits[index]
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <li key={key} style={style} role="listitem" tabIndex={-1} className="p-1 border-b last:border-b-0">
            <LemonButton
                active={activeOption === index}
                to={`https://posthog.com/${slug}`}
                className="[&_>span>span]:flex-col [&_>span>span]:items-start [&_>span>span]:deprecated-space-y-1"
            >
                <span>
                    <span className="flex deprecated-space-x-2 items-center">
                        <p className="m-0 font-bold font-sans line-clamp-1">{title}</p>
                        {type === 'question' && resolved && (
                            <IconCheckCircle className="text-success size-4 flex-shrink-0" />
                        )}
                    </span>
                    <p className="text-xs m-0 opacity-80 font-normal font-sans line-clamp-1">/{slug}</p>
                </span>
            </LemonButton>
        </li>
    )
}

const Hits = ({ activeOption }: { activeOption?: number }): JSX.Element => {
    const { hits } = useHits()
    return (
        <ol role="listbox" className="list-none m-0 p-0 h-[80vh]">
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
        type: 'all',
        label: 'All',
    },
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
    const { refine, items } = useRefinementList({ attribute: 'type' })
    const itemCount = type !== 'all' && items.find(({ value }) => value === type)?.count

    const handleClick = (e: React.MouseEvent<HTMLButtonElement, MouseEvent>): void => {
        e.stopPropagation()
        onClick(type)
    }

    useOnMountEffect(() => refine(type))

    return (
        <button className="p-0 cursor-pointer bg-surface-primary" onClick={handleClick}>
            <LemonTag size="medium" type={active ? 'primary' : 'option'}>
                <span>{label}</span>
                {type !== 'all' && <span>({itemCount ?? 0})</span>}
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
        <ul className="list-none m-0 p-0 flex deprecated-space-x-1 mt-1 mb-0.5 pb-1.5 border-b px-2">
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
            case 'Enter': {
                if (activeOption !== undefined) {
                    openSidePanel(SidePanelTab.Docs, `https://posthog.com/${hits[activeOption].slug}`)
                }
                break
            }

            case 'Escape': {
                setSearchOpen(false)
                break
            }
            case 'ArrowDown': {
                e.preventDefault()
                setActiveOption((currOption) => {
                    if (currOption === undefined || currOption >= hits.length - 1) {
                        return 0
                    }
                    return currOption + 1
                })
                break
            }
            case 'ArrowUp': {
                e.preventDefault()
                setActiveOption((currOption) => {
                    if (currOption !== undefined) {
                        return currOption <= 0 ? hits.length - 1 : currOption - 1
                    }
                })
                break
            }
            case 'Tab':
            case 'ArrowRight': {
                e.preventDefault()
                const currTagIndex = tags.findIndex(({ type }) => type === activeTag)
                setActiveTag(tags[currTagIndex >= tags.length - 1 ? 0 : currTagIndex + 1].type)
                break
            }
            case 'ArrowLeft': {
                e.preventDefault()
                const currTagIndex = tags.findIndex(({ type }) => type === activeTag)
                setActiveTag(tags[currTagIndex <= 0 ? tags.length - 1 : currTagIndex - 1].type)
            }
        }
    }

    useEffect(() => {
        setSearchOpen(!!searchValue)
        setActiveOption(0)
    }, [searchValue])

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
    }, [activeTag, items, refine])

    useOnMountEffect(() => {
        const handleClick = (e: any): void => {
            if (!ref?.current?.contains(e.target)) {
                setSearchOpen(false)
            }
        }

        window.addEventListener('click', handleClick)

        return () => {
            window.removeEventListener('click', handleClick)
        }
    })

    return (
        <div className="relative" ref={ref} onKeyDown={handleKeyDown}>
            <SearchInput value={searchValue} setValue={setSearchValue} />
            {searchOpen && (
                <div className="absolute w-full bg-surface-primary z-50 border rounded-lg shadow-xl mt-0.5">
                    <Tags activeTag={activeTag} setActiveTag={setActiveTag} />
                    <Hits activeOption={activeOption} />
                </div>
            )}
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
