import './Playlist.scss'

import { IconCollapse } from '@posthog/icons'
import { LemonButton, LemonButtonProps, LemonCollapse, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { LemonTableLoader } from 'lib/lemon-ui/LemonTable/LemonTableLoader'
import { range } from 'lib/utils'
import { useEffect, useRef, useState } from 'react'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'

import { Resizer } from '../Resizer/Resizer'

const SCROLL_TRIGGER_OFFSET = 100

export type PlaylistSection = {
    key: string
    title?: string
    items: any[]
    render: ({ item, isActive }: { item: any; isActive: any }) => JSX.Element
    footer?: JSX.Element
}

type PlaylistHeaderAction = Pick<LemonButtonProps, 'icon' | 'tooltip' | 'children'> & {
    key: string
    content: React.ReactNode
}

export type PlaylistProps = {
    sections: PlaylistSection[]
    listEmptyState: JSX.Element
    content: ({ activeItem }: { activeItem: any }) => JSX.Element
    title?: string
    notebooksHref?: string
    embedded?: boolean
    loading?: boolean
    headerActions?: PlaylistHeaderAction[]
    onScrollListEdge?: (edge: 'top' | 'bottom') => void
    onSelect?: (item: any) => void
    'data-attr'?: string
    activeItemId?: string
}

const CounterBadge = ({ children }: { children: React.ReactNode }): JSX.Element => (
    <span className="rounded py-1 px-2 mr-1 text-xs bg-border-light font-semibold select-none">{children}</span>
)

export function Playlist({
    title,
    notebooksHref,
    loading,
    embedded = false,
    activeItemId: propsActiveItemId,
    content,
    sections,
    headerActions = [],
    onScrollListEdge,
    listEmptyState,
    onSelect,
    'data-attr': dataAttr,
}: PlaylistProps): JSX.Element {
    const [controlledActiveItemId, setControlledActiveItemId] = useState<string | null>(null)
    const [listCollapsed, setListCollapsed] = useState<boolean>(false)
    const playlistListRef = useRef<HTMLDivElement>(null)
    const { ref: playlistRef, size } = useResizeBreakpoints({
        0: 'small',
        750: 'medium',
    })

    const onChangeActiveItem = (item: any): void => {
        setControlledActiveItemId(item.id)
        onSelect?.(item.id)
    }

    const activeItemId = propsActiveItemId === undefined ? controlledActiveItemId : propsActiveItemId

    const activeItem = sections.flatMap((s) => s.items).find((i) => i.id === activeItemId)

    return (
        <div
            ref={playlistRef}
            data-attr={dataAttr}
            className={clsx('Playlist', {
                'Playlist--wide': size !== 'small',
                'Playlist--embedded': embedded,
            })}
        >
            <div ref={playlistListRef} className={clsx('Playlist__list', listCollapsed && 'Playlist__list--collapsed')}>
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
                    logicKey="playlist-list"
                    placement="right"
                    containerRef={playlistListRef}
                    closeThreshold={100}
                    onToggleClosed={(value) => setListCollapsed(value)}
                    onDoubleClick={() => setListCollapsed(!listCollapsed)}
                />
            </div>
            <div className="Playlist__main">{content({ activeItem })}</div>
        </div>
    )
}

const CollapsedList = ({ onClickOpen }: { onClickOpen: () => void }): JSX.Element => (
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
    const [activeHeaderActionKey, setActiveHeaderActionKey] = useState<string | null>(null)
    const lastScrollPositionRef = useRef(0)
    const contentRef = useRef<HTMLDivElement | null>(null)

    useEffect(() => {
        if (contentRef.current) {
            contentRef.current.scrollTop = 0
        }
    }, [activeHeaderActionKey])

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

    const actionContent = headerActions?.find((a) => activeHeaderActionKey === a.key)?.content

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
                                    Scrolling to the bottom or the top of the list will load older or newer results
                                    respectively.
                                </>
                            }
                        >
                            <span>
                                <CounterBadge>{Math.min(999, itemsCount)}+</CounterBadge>
                            </span>
                        </Tooltip>
                    </span>
                    {headerActions.map(({ key, icon, tooltip, children }) => (
                        <LemonButton
                            key={key}
                            icon={icon}
                            tooltip={tooltip}
                            size="small"
                            active={activeHeaderActionKey === key}
                            onClick={() => setActiveHeaderActionKey(activeHeaderActionKey === key ? null : key)}
                        >
                            {children}
                        </LemonButton>
                    ))}
                    <LemonTableLoader loading={loading} />
                </div>
            </DraggableToNotebook>

            <div className="overflow-y-auto" onScroll={handleScroll} ref={contentRef}>
                {actionContent && <div className="bg-bg-3000">{actionContent}</div>}

                {sections.flatMap((s) => s.items).length ? (
                    <>
                        {sections.length > 1 ? (
                            <LemonCollapse
                                defaultActiveKeys={sections.map((s) => s.key)}
                                panels={sections.map((s) => ({
                                    key: s.key,
                                    header: s.title,
                                    content: (
                                        <ListSection {...s} activeItemId={activeItemId} onClick={setActiveItemId} />
                                    ),
                                    className: 'p-0',
                                }))}
                                embedded
                                size="small"
                            />
                        ) : (
                            <ListSection {...sections[0]} activeItemId={activeItemId} onClick={setActiveItemId} />
                        )}
                    </>
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
    items,
    render,
    footer,
    onClick,
    activeItemId,
}: PlaylistSection & {
    onClick: (item: any) => void
    activeItemId: string | null
}): JSX.Element => {
    return (
        <>
            {items.length &&
                items.map((item) => (
                    <div key={item.id} className="border-b" onClick={() => onClick(item)}>
                        {render({ item, isActive: item.id === activeItemId })}
                    </div>
                ))}
            {footer}
        </>
    )
}

const LoadingState = (): JSX.Element => {
    return (
        <>
            {range(20).map((i) => (
                <div key={i} className="p-4 space-y-2">
                    <LemonSkeleton className="w-1/2 h-4" />
                    <LemonSkeleton className="w-1/3 h-4" />
                </div>
            ))}
        </>
    )
}
