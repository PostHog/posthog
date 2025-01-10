import './Playlist.scss'

import { IconCollapse } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { LemonTableLoader } from 'lib/lemon-ui/LemonTable/LemonTableLoader'
import { range } from 'lib/utils'
import { ReactNode, useEffect, useRef, useState } from 'react'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'

import { SessionRecordingType } from '~/types'

import { Resizer } from '../Resizer/Resizer'

const SCROLL_TRIGGER_OFFSET = 100

type PlaylistSectionBase = {
    key: string
    title?: string
    initiallyOpen?: boolean
}

export type PlaylistRecordingPreviewBlock = PlaylistSectionBase & {
    items: SessionRecordingType[]
    render: ({ item, isActive }: { item: SessionRecordingType; isActive: boolean }) => JSX.Element
    footer?: JSX.Element
}

export type PlaylistContentBlock = PlaylistSectionBase & {
    content: ReactNode
}

export type PlaylistSection = PlaylistRecordingPreviewBlock | PlaylistContentBlock

export type PlaylistProps = {
    sections: PlaylistSection[]
    listEmptyState: JSX.Element
    content: ReactNode | (({ activeItem }: { activeItem: SessionRecordingType | null }) => JSX.Element) | null
    title?: string
    notebooksHref?: string
    embedded?: boolean
    loading?: boolean
    headerActions?: JSX.Element
    footerActions?: JSX.Element
    onScrollListEdge?: (edge: 'top' | 'bottom') => void
    // Optionally select the first item in the list. Only works in controlled mode
    selectInitialItem?: boolean
    onSelect?: (item: SessionRecordingType) => void
    onChangeSections?: (activeKeys: string[]) => void
    'data-attr'?: string
    activeItemId?: string
    isCollapsed?: boolean
}

const CounterBadge = ({
    children,
    size = 'small',
}: {
    children: React.ReactNode
    size?: 'small' | 'xsmall'
}): JSX.Element => (
    <span
        className={clsx(
            'rounded py-1 px-2 bg-border-light font-semibold select-none',
            size === 'small' ? 'text-xs' : 'text-xxs'
        )}
    >
        {children}
    </span>
)

export function Playlist({
    title,
    notebooksHref,
    loading,
    embedded = false,
    activeItemId: propsActiveItemId,
    content,
    sections,
    headerActions,
    footerActions,
    onScrollListEdge,
    listEmptyState,
    selectInitialItem,
    onSelect,
    onChangeSections,
    isCollapsed = false,
    'data-attr': dataAttr,
}: PlaylistProps): JSX.Element {
    const firstItem = sections
        .filter((s): s is PlaylistRecordingPreviewBlock => 'items' in s)
        ?.find((s) => s.items.length > 0)?.items[0]

    const [controlledActiveItemId, setControlledActiveItemId] = useState<SessionRecordingType['id'] | null>(
        selectInitialItem && firstItem ? firstItem.id : null
    )
    const [listCollapsed, setListCollapsed] = useState<boolean>(isCollapsed)
    useEffect(
        () => {
            if (isCollapsed !== listCollapsed) {
                setListCollapsed(isCollapsed)
            }
        },
        // purposefully only isCollapsed in dependencies
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [isCollapsed]
    )
    const playlistListRef = useRef<HTMLDivElement>(null)
    const { ref: playlistRef, size } = useResizeBreakpoints({
        0: 'small',
        750: 'medium',
    })

    const onChangeActiveItem = (item: SessionRecordingType): void => {
        setControlledActiveItemId(item.id)
        onSelect?.(item)
    }

    const activeItemId = propsActiveItemId === undefined ? controlledActiveItemId : propsActiveItemId

    const activeItem =
        sections
            .filter((s): s is PlaylistRecordingPreviewBlock => 'items' in s)
            .flatMap((s) => s.items)
            .find((i) => i.id === activeItemId) || null

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
                        footerActions={footerActions}
                        onScrollListEdge={onScrollListEdge}
                        onClickCollapse={() => setListCollapsed(true)}
                        activeItemId={activeItemId}
                        setActiveItemId={onChangeActiveItem}
                        onChangeSections={onChangeSections}
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
            {content && (
                <div className="Playlist__main">
                    {typeof content === 'function' ? content({ activeItem }) : content}
                </div>
            )}
        </div>
    )
}

const CollapsedList = ({ onClickOpen }: { onClickOpen: () => void }): JSX.Element => (
    <div className="flex items-start h-full bg-bg-light border-r p-1">
        <LemonButton size="xsmall" icon={<IconChevronRight />} onClick={onClickOpen} />
    </div>
)

function TitleWithCount({
    title,
    count,
    onClickCollapse,
}: {
    title?: string
    count: number
    onClickCollapse: () => void
}): JSX.Element {
    return (
        <div className="flex items-center gap-0.5">
            <LemonButton size="xsmall" icon={<IconCollapse className="rotate-90" />} onClick={onClickCollapse} />
            <span className="flex flex-1 gap-1 items-center">
                {title ? <span className="font-bold uppercase text-xxs tracking-wide">{title}</span> : null}
                <Tooltip
                    placement="bottom"
                    title={
                        <>
                            Showing {count} results.
                            <br />
                            Scrolling to the bottom or the top of the list will load older or newer results
                            respectively.
                        </>
                    }
                >
                    <CounterBadge size="xsmall">{Math.min(999, count)}+</CounterBadge>
                </Tooltip>
            </span>
        </div>
    )
}

function List({
    title,
    notebooksHref,
    onClickCollapse,
    setActiveItemId,
    headerActions,
    footerActions,
    sections,
    onChangeSections,
    activeItemId,
    onScrollListEdge,
    loading,
    emptyState,
}: {
    title?: string
    notebooksHref: PlaylistProps['notebooksHref']
    onClickCollapse: () => void
    activeItemId: SessionRecordingType['id'] | null
    setActiveItemId: (item: SessionRecordingType) => void
    headerActions: PlaylistProps['headerActions']
    footerActions: PlaylistProps['footerActions']
    sections: PlaylistProps['sections']
    onChangeSections?: (activeKeys: string[]) => void
    onScrollListEdge: PlaylistProps['onScrollListEdge']
    loading: PlaylistProps['loading']
    emptyState: PlaylistProps['listEmptyState']
}): JSX.Element {
    const lastScrollPositionRef = useRef(0)
    const contentRef = useRef<HTMLDivElement | null>(null)

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

    const itemsCount = sections
        .filter((s): s is PlaylistRecordingPreviewBlock => 'items' in s)
        .flatMap((s) => s.items).length
    const initiallyOpenSections = sections.filter((s) => s.initiallyOpen).map((s) => s.key)

    return (
        <div className="flex flex-col w-full bg-bg-light overflow-hidden border-r h-full">
            <DraggableToNotebook href={notebooksHref}>
                <div className="flex flex-col gap-1">
                    <div className="shrink-0 bg-bg-3000 relative flex justify-between items-center gap-0.5 whitespace-nowrap border-b">
                        <TitleWithCount title={title} count={itemsCount} onClickCollapse={onClickCollapse} />
                        {headerActions}
                    </div>
                    <LemonTableLoader loading={loading} />
                </div>
            </DraggableToNotebook>
            <div className="overflow-y-auto flex-1" onScroll={handleScroll} ref={contentRef}>
                {sections.filter((s): s is PlaylistRecordingPreviewBlock => 'items' in s).flatMap((s) => s.items)
                    .length ? (
                    <>
                        <LemonCollapse
                            defaultActiveKeys={initiallyOpenSections}
                            panels={sections.map((s) => {
                                const content =
                                    'items' in s ? (
                                        <ListSection {...s} activeItemId={activeItemId} onClick={setActiveItemId} />
                                    ) : (
                                        s.content
                                    )
                                return {
                                    key: s.key,
                                    header: s.title,
                                    content,
                                    className: 'p-0',
                                }
                            })}
                            onChange={onChangeSections}
                            multiple
                            embedded
                            size="small"
                        />
                    </>
                ) : loading ? (
                    <LoadingState />
                ) : (
                    emptyState
                )}
            </div>
            <div className="shrink-0 relative flex justify-between items-center gap-0.5 whitespace-nowrap border-t">
                {footerActions}
            </div>
        </div>
    )
}

export function ListSection({
    items,
    render,
    footer,
    onClick,
    activeItemId,
}: PlaylistRecordingPreviewBlock & {
    onClick: (item: SessionRecordingType) => void
    activeItemId: SessionRecordingType['id'] | null
}): JSX.Element {
    return (
        <>
            {items.length > 0
                ? items.map((item) => (
                      <div key={item.id} className="border-b" onClick={() => onClick(item)}>
                          {render({ item, isActive: item.id === activeItemId })}
                      </div>
                  ))
                : null}
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
