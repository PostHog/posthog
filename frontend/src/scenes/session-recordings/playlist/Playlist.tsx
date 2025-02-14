import './Playlist.scss'

import { IconAIText, IconX } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonSkeleton, LemonTag, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { LemonTableLoader } from 'lib/lemon-ui/LemonTable/LemonTableLoader'
import { range } from 'lib/utils'
import { ReactNode, useRef, useState } from 'react'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { AiFilter } from 'scenes/session-recordings/components/AiFilter/AiFilter'

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

    const [isExpanded, setIsExpanded] = useState(false)

    const onChangeActiveItem = (item: SessionRecordingType): void => {
        setControlledActiveItemId(item.id)
        onSelect?.(item)
    }

    const initiallyOpenSections = sections.filter((s) => s.initiallyOpen).map((s) => s.key)
    const [openSections, setOpenSections] = useState<string[]>(initiallyOpenSections)

    const onChangeOpenSections = (activeKeys: string[]): void => {
        setOpenSections(activeKeys)
        onChangeSections?.(activeKeys)
    }

    const activeItemId = propsActiveItemId === undefined ? controlledActiveItemId : propsActiveItemId

    const activeItem =
        sections
            .filter((s): s is PlaylistRecordingPreviewBlock => 'items' in s)
            .flatMap((s) => s.items)
            .find((i) => i.id === activeItemId) || null

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

    const sectionCount = sections.length
    const itemsCount = sections
        .filter((s): s is PlaylistRecordingPreviewBlock => 'items' in s)
        .flatMap((s) => s.items).length

    return (
        <>
            <div
                className={clsx(`w-full mb-8`, {
                    hidden: !isExpanded,
                })}
            >
                <div className="flex justify-end">
                    <LemonButton icon={<IconX />} onClick={() => setIsExpanded(false)} />
                </div>
                <AiFilter />
            </div>

            <div
                className={clsx('flex flex-col w-full gap-2 h-full', {
                    'xl:flex-row': true,
                })}
            >
                <div className="flex flex-col gap-2 xl:max-w-80">
                    {!isExpanded && (
                        <FlaggedFeature flag={FEATURE_FLAGS.RECORDINGS_AI_FILTER}>
                            <div className="flex justify-center">
                                <LemonButton
                                    fullWidth
                                    type="secondary"
                                    className="bg-white"
                                    icon={<IconAIText />}
                                    onClick={() => setIsExpanded(true)}
                                >
                                    Ask Max AI about recordings{' '}
                                    <LemonTag type="completion" className="ml-2">
                                        ALPHA
                                    </LemonTag>
                                </LemonButton>
                            </div>
                        </FlaggedFeature>
                    )}
                    <div
                        ref={playlistRef}
                        data-attr={dataAttr}
                        className={clsx('Playlist w-full min-w-60 min-h-96', {
                            'Playlist--wide': size !== 'small',
                            'Playlist--embedded': embedded,
                        })}
                    >
                        <div
                            ref={playlistListRef}
                            className="Playlist__list flex flex-col relative overflow-hidden h-full w-full"
                        >
                            <DraggableToNotebook href={notebooksHref}>{filterActions}</DraggableToNotebook>

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
                                    {sectionCount > 1 ? (
                                        <LemonCollapse
                                            defaultActiveKeys={openSections}
                                            panels={sections.map((s) => {
                                                return {
                                                    key: s.key,
                                                    header: s.title ?? '',
                                                    content: (
                                                        <SectionContent
                                                            section={s}
                                                            loading={!!loading}
                                                            setActiveItemId={onChangeActiveItem}
                                                            activeItemId={activeItemId}
                                                            emptyState={listEmptyState}
                                                        />
                                                    ),
                                                    className: 'p-0',
                                                }
                                            })}
                                            onChange={onChangeOpenSections}
                                            multiple
                                            embedded
                                            size="small"
                                        />
                                    ) : sectionCount === 1 ? (
                                        <SectionContent
                                            section={sections[0]}
                                            loading={!!loading}
                                            setActiveItemId={onChangeActiveItem}
                                            activeItemId={activeItemId}
                                            emptyState={listEmptyState}
                                        />
                                    ) : loading ? (
                                        <LoadingState />
                                    ) : (
                                        listEmptyState
                                    )}
                                </div>
                                <div className="shrink-0 relative flex justify-between items-center gap-0.5 whitespace-nowrap">
                                    {footerActions}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <div
                    className={clsx(
                        'Playlist h-full min-h-96 w-full min-w-96 lg:min-w-[560px] order-first xl:order-none',
                        {
                            'Playlist--wide': size !== 'small',
                            'Playlist--embedded': embedded,
                        }
                    )}
                >
                    {content && (
                        <div className="Playlist__main h-full">
                            {' '}
                            {typeof content === 'function' ? content({ activeItem }) : content}
                        </div>
                    )}
                </div>
            </div>
        </>
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

function SectionContent({
    section,
    loading,
    activeItemId,
    setActiveItemId,
    emptyState,
}: {
    section: PlaylistSection
    loading: boolean
    activeItemId: SessionRecordingType['id'] | null
    setActiveItemId: (item: SessionRecordingType) => void
    emptyState: PlaylistProps['listEmptyState']
}): JSX.Element {
    return 'content' in section ? (
        <>{section.content}</>
    ) : 'items' in section && !!section.items.length ? (
        <ListSection {...section} onClick={setActiveItemId} activeItemId={activeItemId} />
    ) : loading ? (
        <LoadingState />
    ) : (
        emptyState
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
