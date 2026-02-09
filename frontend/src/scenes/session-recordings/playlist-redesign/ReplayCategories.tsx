import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import {
    IconChevronLeft,
    IconChevronRight,
    IconCursorClick,
    IconFolder,
    IconGraph,
    IconPhone,
    IconSearch,
    IconSparkles,
} from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { IconErrorOutline } from 'lib/lemon-ui/icons'

import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, RecordingUniversalFilters } from '~/types'

import { playlistFiltersLogic } from '../playlist/playlistFiltersLogic'
import {
    SessionRecordingPlaylistLogicProps,
    sessionRecordingsPlaylistLogic,
} from '../playlist/sessionRecordingsPlaylistLogic'

interface ReplayCategory {
    id: string
    label: string
    icon: JSX.Element
    description: string
    action: 'apply_filter' | 'open_saved_filters' | 'clear_filters' | 'show_content'
    filters?: Partial<RecordingUniversalFilters>
    activeColorClass: string
}

const REPLAY_CATEGORIES: ReplayCategory[] = [
    {
        id: 'browse',
        label: 'Browse',
        icon: <IconSearch className="text-blue-600" />,
        description: 'View all recordings',
        action: 'clear_filters',
        activeColorClass: 'bg-blue-100 border-blue-600',
    },
    {
        id: 'mobile',
        label: 'Mobile',
        icon: <IconPhone className="text-purple-600" />,
        description: 'Recordings from mobile devices',
        action: 'apply_filter',
        activeColorClass: 'bg-purple-100 border-purple-600',
        filters: {
            filter_group: {
                type: FilterLogicalOperator.And,
                values: [
                    {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: PropertyFilterType.Event,
                                key: '$device_type',
                                operator: PropertyOperator.Exact,
                                value: ['Mobile'],
                            },
                        ],
                    },
                ],
            },
        },
    },
    {
        id: 'high_errors',
        label: 'High errors',
        icon: <IconErrorOutline className="text-red-600" />,
        description: 'Recordings with errors or exceptions',
        action: 'apply_filter',
        activeColorClass: 'bg-red-100 border-red-600',
        filters: {
            filter_group: {
                type: FilterLogicalOperator.And,
                values: [
                    {
                        type: FilterLogicalOperator.Or,
                        values: [
                            {
                                type: PropertyFilterType.Session,
                                key: 'console_error_count',
                                operator: PropertyOperator.GreaterThan,
                                value: 5,
                            },
                            {
                                type: PropertyFilterType.Session,
                                key: 'exception_count',
                                operator: PropertyOperator.GreaterThan,
                                value: 0,
                            },
                        ],
                    },
                ],
            },
        },
    },
    {
        id: 'engaged',
        label: 'Engaged',
        icon: <IconCursorClick className="text-green-600" />,
        description: 'Recordings with high interaction',
        action: 'apply_filter',
        activeColorClass: 'bg-green-100 border-green-600',
        filters: {
            filter_group: {
                type: FilterLogicalOperator.And,
                values: [
                    {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: PropertyFilterType.Session,
                                key: 'click_count',
                                operator: PropertyOperator.GreaterThan,
                                value: 20,
                            },
                        ],
                    },
                ],
            },
        },
    },
    {
        id: 'saved_filters',
        label: 'Saved filters',
        icon: <IconSparkles className="text-yellow-600" />,
        description: 'Open your saved filter presets',
        action: 'show_content',
        activeColorClass: 'bg-yellow-100 border-yellow-600',
    },
    {
        id: 'collections',
        label: 'Collections',
        icon: <IconFolder className="text-indigo-600" />,
        description: 'View and create recording collections',
        action: 'show_content',
        activeColorClass: 'bg-indigo-100 border-indigo-600',
    },
    {
        id: 'quick_stats',
        label: 'Insights',
        icon: <IconGraph className="text-teal-600" />,
        description: 'Most seen pages, users, and visit times',
        action: 'show_content',
        activeColorClass: 'bg-teal-100 border-teal-600',
    },
]

export function ReplayCategories({ logicKey }: SessionRecordingPlaylistLogicProps): JSX.Element {
    const logic = sessionRecordingsPlaylistLogic({ logicKey })
    const { setFilters, resetFilters } = useActions(logic)
    const { activeCategory } = useValues(playlistFiltersLogic)
    const { setActiveCategory } = useActions(playlistFiltersLogic)

    const scrollContainerRef = useRef<HTMLDivElement>(null)
    const [showLeftArrow, setShowLeftArrow] = useState(false)
    const [showRightArrow, setShowRightArrow] = useState(false)

    const handleCategoryClick = (category: ReplayCategory): void => {
        setActiveCategory(category.id)

        if (category.action === 'clear_filters') {
            resetFilters()
        } else if (category.action === 'apply_filter' && category.filters) {
            setFilters(category.filters)
        }
        // 'show_content' action just sets the active category, content is shown by parent component
    }

    const updateArrowVisibility = (): void => {
        const container = scrollContainerRef.current
        if (!container) {
            return
        }

        const { scrollLeft, scrollWidth, clientWidth } = container
        setShowLeftArrow(scrollLeft > 0)
        setShowRightArrow(scrollLeft < scrollWidth - clientWidth - 1)
    }

    const scroll = (direction: 'left' | 'right'): void => {
        const container = scrollContainerRef.current
        if (!container) {
            return
        }

        const scrollAmount = 300
        container.scrollBy({
            left: direction === 'left' ? -scrollAmount : scrollAmount,
            behavior: 'smooth',
        })
    }

    useEffect(() => {
        const container = scrollContainerRef.current
        if (!container) {
            return
        }

        updateArrowVisibility()

        const handleScroll = (): void => {
            updateArrowVisibility()
        }

        const handleResize = (): void => {
            updateArrowVisibility()
        }

        container.addEventListener('scroll', handleScroll)
        window.addEventListener('resize', handleResize)

        return () => {
            container.removeEventListener('scroll', handleScroll)
            window.removeEventListener('resize', handleResize)
        }
    }, [])

    return (
        <div className="relative bg-surface-primary border-b border-border-primary">
            {showLeftArrow && (
                <div className="absolute left-0 top-0 bottom-0 z-10 flex items-center pointer-events-none">
                    <div className="pointer-events-auto pl-2">
                        <LemonButton
                            type="primary"
                            size="large"
                            icon={<IconChevronLeft />}
                            onClick={() => scroll('left')}
                            data-attr="replay-categories-scroll-left"
                            className="shadow-lg bg-bg-light"
                        />
                    </div>
                </div>
            )}

            <div
                ref={scrollContainerRef}
                className="flex gap-4 p-4 overflow-x-auto scrollbar-hide"
                style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}
            >
                {REPLAY_CATEGORIES.map((category) => {
                    const isActive = activeCategory === category.id

                    return (
                        <div
                            key={category.id}
                            role="button"
                            tabIndex={0}
                            className={clsx(
                                'flex flex-col items-start gap-2 px-4 py-3 rounded cursor-pointer transition-all min-w-48 max-w-64 flex-shrink-0',
                                'border-2 hover:shadow-md',
                                isActive
                                    ? category.activeColorClass
                                    : 'bg-surface-secondary border-border hover:border-border-bold hover:bg-surface-light'
                            )}
                            onClick={() => handleCategoryClick(category)}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                    e.preventDefault()
                                    handleCategoryClick(category)
                                }
                            }}
                            data-attr={`replay-category-${category.id}`}
                        >
                            <div className="text-2xl">{category.icon}</div>
                            <div className="flex flex-col gap-1">
                                <div className="text-base font-semibold">{category.label}</div>
                                <div className={clsx('text-xs', isActive ? 'text-default' : 'text-muted')}>
                                    {category.description}
                                </div>
                            </div>
                        </div>
                    )
                })}
            </div>

            {showRightArrow && (
                <div className="absolute right-0 top-0 bottom-0 z-10 flex items-center pointer-events-none">
                    <div className="pointer-events-auto pr-2">
                        <LemonButton
                            type="primary"
                            size="large"
                            icon={<IconChevronRight />}
                            onClick={() => scroll('right')}
                            data-attr="replay-categories-scroll-right"
                            className="shadow-lg bg-bg-light"
                        />
                    </div>
                </div>
            )}
        </div>
    )
}
