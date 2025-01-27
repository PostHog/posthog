import './Playlist.scss'

import { LemonCollapse, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { LemonTableLoader } from 'lib/lemon-ui/LemonTable/LemonTableLoader'
import { range } from 'lib/utils'
import { ReactNode, useRef, useState } from 'react'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'

import { SessionRecordingType } from '~/types'

const SCROLL_TRIGGER_OFFSET = 100

type PlaylistSectionBase = {
    key: string
    title?: ReactNode
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
    filterActions?: JSX.Element | null
    onScrollListEdge?: (edge: 'top' | 'bottom') => void
    // Optionally select the first item in the list. Only works in controlled mode
    selectInitialItem?: boolean
    onSelect?: (item: SessionRecordingType) => void
    onChangeSections?: (activeKeys: string[]) => void
    'data-attr'?: string
    activeItemId?: string
    isCollapsed?: boolean
}

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
    filterActions,
    onScrollListEdge,
    listEmptyState,
    selectInitialItem,
    onSelect,
    onChangeSections,
    'data-attr': dataAttr,
}: PlaylistProps): JSX.Element {
    const firstItem = sections
        .filter((s): s is PlaylistRecordingPreviewBlock => 'items' in s)
        ?.find((s) => s.items.length > 0)?.items[0]

    const [controlledActiveItemId, setControlledActiveItemId] = useState<SessionRecordingType['id'] | null>(
        selectInitialItem && firstItem ? firstItem.id : null
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
        <div className="flex flex-col xl:flex-row w-full gap-2 h-full">
            <div
                ref={playlistRef}
                data-attr={dataAttr}
                className={clsx('Playlist w-full xl:max-w-80 min-w-60 min-h-96', {
                    'Playlist--wide': size !== 'small',
                    'Playlist--embedded': embedded,
                })}
            >
                <div
                    ref={playlistListRef}
                    className="Playlist__list flex flex-col relative overflow-hidden h-full w-full"
                >
                    <DraggableToNotebook href={notebooksHref}>{filterActions}</DraggableToNotebook>

                    <List
                        title={title}
                        notebooksHref={notebooksHref}
                        loading={loading}
                        sections={sections}
                        headerActions={headerActions}
                        footerActions={footerActions}
                        onScrollListEdge={onScrollListEdge}
                        activeItemId={activeItemId}
                        setActiveItemId={onChangeActiveItem}
                        onChangeSections={onChangeSections}
                        emptyState={listEmptyState}
                    />
                </div>
            </div>
            <div
                className={clsx('Playlist h-full min-h-96 w-full min-w-96 lg:min-w-[560px] order-first xl:order-none', {
                    'Playlist--wide': size !== 'small',
                    'Playlist--embedded': embedded,
                })}
            >
                {content && (
                    <div className="Playlist__main h-full">
                        {' '}
                        {typeof content === 'function' ? content({ activeItem }) : content}
                    </div>
                )}
            </div>
        </div>
    )
}

const TitleWithCount = ({ title, count }: { title?: string; count: number }): JSX.Element => {
    return (
        <div className="flex items-center gap-0.5">
            {title && (
                <span className="flex flex-1 gap-1 items-center">
                    <span className="font-bold uppercase text-xxs tracking-wide">{title}</span>
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
                        <span className="rounded py-1 px-2 bg-border-light font-semibold select-none text-xxs">
                            {Math.min(999, count)}+
                        </span>
                    </Tooltip>
                </span>
            )}
        </div>
    )
}

const List = ({
    title,
    notebooksHref,
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
    activeItemId: SessionRecordingType['id'] | null
    setActiveItemId: (item: SessionRecordingType) => void
    headerActions: PlaylistProps['headerActions']
    footerActions: PlaylistProps['footerActions']
    sections: PlaylistProps['sections']
    onChangeSections?: (activeKeys: string[]) => void
    onScrollListEdge: PlaylistProps['onScrollListEdge']
    loading: PlaylistProps['loading']
    emptyState: PlaylistProps['listEmptyState']
}): JSX.Element => {
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
        <div className="flex flex-col relative w-full bg-bg-light overflow-hidden h-full Playlist__list">
            <DraggableToNotebook href={notebooksHref}>
                <div className="flex flex-col gap-1">
                    <div className="shrink-0 bg-bg-3000 relative flex justify-between items-center gap-0.5 whitespace-nowrap border-b">
                        {title && <TitleWithCount title={title} count={itemsCount} />}
                        {headerActions}
                    </div>
                    <LemonTableLoader loading={loading} />
                </div>
            </DraggableToNotebook>
            <div className="overflow-y-auto flex-1" onScroll={handleScroll} ref={contentRef}>
                <LemonCollapse
                    defaultActiveKeys={initiallyOpenSections}
                    panels={sections.map((s) => {
                        const content =
                            'content' in s ? (
                                s.content
                            ) : 'items' in s && !!s.items.length ? (
                                <ListSection {...s} onClick={setActiveItemId} activeItemId={activeItemId} />
                            ) : loading ? (
                                <LoadingState />
                            ) : (
                                emptyState
                            )

                        return {
                            key: s.key,
                            header: s.title ?? '',
                            content,
                            className: 'p-0',
                        }
                    })}
                    onChange={onChangeSections}
                    multiple
                    embedded
                    size="small"
                />
            </div>
            <div className="shrink-0 relative flex justify-between items-center gap-0.5 whitespace-nowrap">
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
            {range(5).map((i) => (
                <div key={i} className="p-4 space-y-2">
                    <LemonSkeleton className="w-1/2 h-4" />
                    <LemonSkeleton className="w-1/3 h-4" />
                </div>
            ))}
        </>
    )
}
