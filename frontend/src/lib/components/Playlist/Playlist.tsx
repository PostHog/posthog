import clsx from 'clsx'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { useEffect, useRef, useState } from 'react'
import { Resizer } from '../Resizer/Resizer'
import { LemonButton, LemonButtonProps, LemonSkeleton, Spinner, Tooltip } from '@posthog/lemon-ui'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { IconCollapse } from '@posthog/icons'
import { range } from 'lib/utils'
import { EmptyMessage } from '../EmptyMessage/EmptyMessage'
import { LemonTableLoader } from 'lib/lemon-ui/LemonTable/LemonTableLoader'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'

const SCROLL_TRIGGER_OFFSET = 100

export type PlaylistSection = {
    title?: string
    items: any[]
    render: ({ item, isActive }: { item: any; isActive: any }) => JSX.Element
    collapsible?: boolean
}

type PlaylistHeaderAction = Pick<LemonButtonProps, 'icon' | 'tooltip'> & {
    key: string
    content: React.ReactNode
}

type PlaylistProps = {
    title?: string
    notebooksHref?: string
    embedded: boolean
    sections: PlaylistSection[]
    loading?: boolean
    headerActions?: PlaylistHeaderAction[]
    onScrollListEdge?: (edge: 'top' | 'bottom') => void
    listEmptyState: JSX.Element
    onSelect: (item: any) => void
    content: ({ activeItem }: { activeItem: any }) => JSX.Element
}

const CounterBadge = ({ children }: { children: React.ReactNode }): JSX.Element => (
    <span className="rounded py-1 px-2 mr-1 text-xs bg-border-light font-semibold select-none">{children}</span>
)

export function Playlist({
    title,
    notebooksHref,
    embedded,
    content,
    sections,
    loading,
    headerActions = [],
    onScrollListEdge,
    listEmptyState,
    onSelect,
}: PlaylistProps): JSX.Element {
    const [activeItemId, setActiveItemId] = useState<string | null>(null)
    const [listCollapsed, setListCollapsed] = useState<boolean>(false)
    const playlistRecordingsListRef = useRef<HTMLDivElement>(null)
    const { ref: playlistRef, size } = useResizeBreakpoints({
        0: 'small',
        750: 'medium',
    })

    const onChangeActiveItem = (item: any) => {
        setActiveItemId(item.id)
        onSelect(item.id)
    }

    return (
        <div
            ref={playlistRef}
            data-attr="session-recordings-playlist"
            className={clsx('Playlist', {
                'Playlist--wide': size !== 'small',
                'Playlist--embedded': embedded,
            })}
        >
            <div
                ref={playlistRecordingsListRef}
                className={clsx('Playlist__list', listCollapsed && 'Playlist__list--collapsed')}
            >
                {listCollapsed ? (
                    <CollapsedList onClickOpen={() => setListCollapsed(false)} />
                ) : (
                    <List
                        title={title}
                        notebooksHref={notebooksHref}
                        loading={loading}
                        sections={sections}
                        headerActions={headerActions}
                        onScrollListEdge={onScrollListEdge}
                        onClickCollapse={() => setListCollapsed(true)}
                        activeItemId={activeItemId}
                        setActiveItemId={onChangeActiveItem}
                        emptyState={listEmptyState}
                    />
                )}
                <Resizer
                    logicKey="player-recordings-list"
                    placement="right"
                    containerRef={playlistRecordingsListRef}
                    closeThreshold={100}
                    onToggleClosed={(value) => setListCollapsed(value)}
                    onDoubleClick={() => setListCollapsed(!listCollapsed)}
                />
            </div>
            <div className="Playlist__player">
                {!activeItemId ? (
                    <div className="mt-20">
                        <EmptyMessage
                            title="No recording selected"
                            description="Please select a recording from the list on the left"
                            buttonText="Learn more about recordings"
                            buttonTo="https://posthog.com/docs/user-guides/recordings"
                        />
                    </div>
                ) : (
                    content
                )}
            </div>
        </div>
    )
}

const CollapsedList = ({ onClickOpen }: { onClickOpen: () => void }) => (
    <div className="flex items-start h-full bg-bg-light border-r p-1">
        <LemonButton size="small" icon={<IconChevronRight />} onClick={onClickOpen} />
    </div>
)

const List = ({
    title,
    notebooksHref,
    onClickCollapse,
    setActiveItemId,
    headerActions = [],
    sections,
    activeItemId,
    onScrollListEdge,
    loading,
    emptyState,
}: {
    title: PlaylistProps['title']
    notebooksHref: PlaylistProps['notebooksHref']
    onClickCollapse: () => void
    activeItemId: string | null
    setActiveItemId: (id: string) => void
    headerActions: PlaylistProps['headerActions']
    sections: PlaylistProps['sections']
    onScrollListEdge: PlaylistProps['onScrollListEdge']
    loading: PlaylistProps['loading']
    emptyState: PlaylistProps['listEmptyState']
}): JSX.Element => {
    const [activeHeaderAction, setActiveHeaderAction] = useState<string | null>(null)
    const lastScrollPositionRef = useRef(0)
    const contentRef = useRef<HTMLDivElement | null>(null)

    useEffect(() => {
        if (contentRef.current) {
            contentRef.current.scrollTop = 0
        }
    }, [activeHeaderAction])

    const handleScroll = (e: React.UIEvent<HTMLDivElement>): void => {
        // If we are scrolling down then check if we are at the bottom of the list
        if (e.currentTarget.scrollTop > lastScrollPositionRef.current) {
            const scrollPosition = e.currentTarget.scrollTop + e.currentTarget.clientHeight
            if (e.currentTarget.scrollHeight - scrollPosition < SCROLL_TRIGGER_OFFSET) {
                onScrollListEdge?.('bottom')
            }
        }

        // Same again but if scrolling to the top
        if (e.currentTarget.scrollTop < lastScrollPositionRef.current) {
            if (e.currentTarget.scrollTop < SCROLL_TRIGGER_OFFSET) {
                onScrollListEdge?.('top')
            }
        }

        lastScrollPositionRef.current = e.currentTarget.scrollTop
    }

    const ActiveAction = headerActions?.find((a) => activeHeaderAction === a.key)?.content

    const itemsCount = sections.flatMap((s) => s.items).length

    return (
        <div className="flex flex-col w-full bg-bg-light overflow-hidden border-r h-full">
            <DraggableToNotebook href={notebooksHref}>
                <div className="shrink-0 relative flex justify-between items-center p-1 gap-1 whitespace-nowrap border-b">
                    <LemonButton size="small" icon={<IconCollapse className="rotate-90" />} onClick={onClickCollapse} />
                    <span className="py-1 flex flex-1 gap-2">
                        {title ? (
                            <span className="font-bold uppercase text-xs my-1 tracking-wide flex gap-1 items-center">
                                {title}
                            </span>
                        ) : null}
                        <Tooltip
                            placement="bottom"
                            title={
                                <>
                                    Showing {itemsCount} results.
                                    <br />
                                    Scrolling to the bottom or the top of the list will load older or newer recordings
                                    respectively.
                                </>
                            }
                        >
                            <span>
                                <CounterBadge>{Math.min(999, itemsCount)}+</CounterBadge>
                            </span>
                        </Tooltip>
                    </span>
                    {headerActions.map((action) => (
                        <LemonButton size="small" {...action} onClick={() => setActiveHeaderAction(action.key)} />
                    ))}
                    <LemonTableLoader loading={loading} />
                </div>
            </DraggableToNotebook>

            <div className={clsx('overflow-y-auto')} onScroll={handleScroll} ref={contentRef}>
                {/* {ActiveAction && <ActiveAction />} */}

                {sections.flatMap((s) => s.items).length ? (
                    <ul>
                        {sections.map((s) => (
                            <ListSection {...s} activeItemId={activeItemId} onClick={setActiveItemId} />
                        ))}
                        <div className="m-4 h-10 flex items-center justify-center gap-2 text-muted-alt">
                            {/* {!showOtherRecordings && totalFiltersCount ? (
                                    <>Filters do not apply to pinned recordings</>
                                ) : loading ? (
                                    <>
                                        <Spinner textColored /> Loading older recordings
                                    </>
                                ) : hasNext ? (
                                    <LemonButton onClick={() => maybeLoadSessionRecordings('older')}>
                                        Load more
                                    </LemonButton>
                                ) : (
                                    'No more results'
                                )} */}
                        </div>
                    </ul>
                ) : loading ? (
                    <LoadingState />
                ) : (
                    emptyState
                )}
            </div>
        </div>
    )
}

const ListSection = ({
    title,
    items,
    render,
    onClick,
    collapsible,
    activeItemId,
}: PlaylistSection & {
    onClick: (item: any) => void
    activeItemId: string | null
}) => {
    return (
        <>
            {title && (
                <div className="flex justify-between items-center pl-3 pr-1 py-2 text-muted-alt border-b uppercase font-semibold text-xs">
                    {title}
                    {/* {collapsible && <LemonButton size="xsmall" onClick={() => toggleShowOtherRecordings()}>
                        {showOtherRecordings ? 'Hide' : 'Show'}
                    </LemonButton>} */}
                </div>
            )}
            {items.length &&
                items.map((item) => (
                    <li key={item.id} className="border-b" onClick={() => onClick(item)}>
                        {render({ item, isActive: item.id === activeItemId })}
                    </li>
                ))}
        </>
    )
}

const LoadingState = () => {
    return (
        <>
            {range(20).map(() => (
                <div className="p-4 space-y-2">
                    <LemonSkeleton className="w-1/2 h-4" />
                    <LemonSkeleton className="w-1/3 h-4" />
                </div>
            ))}
        </>
    )
}
