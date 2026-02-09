import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconCursorClick, IconPhone, IconSearch, IconSparkles } from '@posthog/icons'

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
    action: 'apply_filter' | 'open_saved_filters' | 'clear_filters'
    filters?: Partial<RecordingUniversalFilters>
}

const REPLAY_CATEGORIES: ReplayCategory[] = [
    {
        id: 'browse',
        label: 'Browse',
        icon: <IconSearch />,
        description: 'View all recordings',
        action: 'clear_filters',
    },
    {
        id: 'mobile',
        label: 'Mobile',
        icon: <IconPhone />,
        description: 'Recordings from mobile devices',
        action: 'apply_filter',
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
        icon: <IconErrorOutline />,
        description: 'Recordings with errors or exceptions',
        action: 'apply_filter',
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
        icon: <IconCursorClick />,
        description: 'Recordings with high interaction',
        action: 'apply_filter',
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
        icon: <IconSparkles />,
        description: 'Open your saved filter presets',
        action: 'open_saved_filters',
    },
]

export function ReplayCategories({ logicKey }: SessionRecordingPlaylistLogicProps): JSX.Element {
    const logic = sessionRecordingsPlaylistLogic({ logicKey })
    const { setFilters, resetFilters } = useActions(logic)
    const { activeCategory } = useValues(playlistFiltersLogic)
    const { setActiveCategory, setIsFiltersExpanded, setActiveFilterTab } = useActions(playlistFiltersLogic)

    const handleCategoryClick = (category: ReplayCategory): void => {
        setActiveCategory(category.id)

        if (category.action === 'clear_filters') {
            resetFilters()
        } else if (category.action === 'apply_filter' && category.filters) {
            setFilters(category.filters)
        } else if (category.action === 'open_saved_filters') {
            setActiveFilterTab('saved')
            setIsFiltersExpanded(true)
        }
    }

    return (
        <div className="flex gap-4 p-4 bg-surface-primary border-b border-border-primary flex-wrap">
            {REPLAY_CATEGORIES.map((category) => {
                const isActive = activeCategory === category.id

                return (
                    <div
                        key={category.id}
                        role="button"
                        tabIndex={0}
                        className={clsx(
                            'flex flex-col items-start gap-3 px-5 py-4 rounded cursor-pointer transition-all min-w-48 max-w-64',
                            'border-2 hover:shadow-md',
                            isActive
                                ? 'bg-primary-highlight border-primary'
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
                        <div className={clsx('text-3xl', isActive && 'text-primary')}>{category.icon}</div>
                        <div className="flex flex-col gap-1">
                            <div className={clsx('text-base font-semibold', isActive && 'text-primary')}>
                                {category.label}
                            </div>
                            <div className={clsx('text-xs', isActive ? 'text-primary' : 'text-muted')}>
                                {category.description}
                            </div>
                        </div>
                    </div>
                )
            })}
        </div>
    )
}
