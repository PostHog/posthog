import { useState } from 'react'

import {
    IconChevronDown,
    IconClock,
    IconComment,
    IconDashboard,
    IconDatabase,
    IconFlag,
    IconFlask,
    IconGraph,
    IconRewindPlay,
} from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { FeedActivityType, FeedItem } from '~/types'

import { FeedItemThread } from './FeedItemThread'

interface FeedGroupedCardProps {
    items: FeedItem[]
    type: FeedActivityType
}

function getActivityIcon(type: FeedActivityType): JSX.Element {
    const iconMap: Record<FeedActivityType, JSX.Element> = {
        [FeedActivityType.Dashboard]: <IconDashboard />,
        [FeedActivityType.EventDefinition]: <IconGraph />,
        [FeedActivityType.ExperimentLaunched]: <IconFlask />,
        [FeedActivityType.ExperimentCompleted]: <IconFlask />,
        [FeedActivityType.FeatureFlag]: <IconFlag />,
        [FeedActivityType.Survey]: <IconComment />,
        [FeedActivityType.ReplayPlaylist]: <IconRewindPlay />,
        [FeedActivityType.ExpiringRecordings]: <IconClock />,
        [FeedActivityType.ExternalDataSource]: <IconDatabase />,
    }
    return iconMap[type] || <IconGraph />
}

function getActivityTypeLabel(type: FeedActivityType, count: number): string {
    const labels: Record<FeedActivityType, string> = {
        [FeedActivityType.Dashboard]: count === 1 ? 'Dashboard' : 'Dashboards',
        [FeedActivityType.EventDefinition]: count === 1 ? 'Event' : 'Events',
        [FeedActivityType.ExperimentLaunched]: count === 1 ? 'Experiment launched' : 'Experiments launched',
        [FeedActivityType.ExperimentCompleted]: count === 1 ? 'Experiment completed' : 'Experiments completed',
        [FeedActivityType.ExternalDataSource]: count === 1 ? 'Data source' : 'Data sources',
        [FeedActivityType.FeatureFlag]: count === 1 ? 'Feature flag' : 'Feature flags',
        [FeedActivityType.Survey]: count === 1 ? 'Survey' : 'Surveys',
        [FeedActivityType.ReplayPlaylist]: count === 1 ? 'Replay playlist' : 'Replay playlists',
        [FeedActivityType.ExpiringRecordings]: count === 1 ? 'Expiring recording' : 'Expiring recordings',
    }
    return labels[type] || type
}

function getBorderColor(type: FeedActivityType): string {
    const borderColors: Record<FeedActivityType, string> = {
        [FeedActivityType.Dashboard]: 'border-l-primary',
        [FeedActivityType.EventDefinition]: 'border-l-success',
        [FeedActivityType.ExperimentLaunched]: 'border-l-warning',
        [FeedActivityType.ExperimentCompleted]: 'border-l-success',
        [FeedActivityType.FeatureFlag]: 'border-l-primary',
        [FeedActivityType.Survey]: 'border-l-purple',
        [FeedActivityType.ReplayPlaylist]: 'border-l-danger',
        [FeedActivityType.ExpiringRecordings]: 'border-l-muted',
        [FeedActivityType.ExternalDataSource]: 'border-l-primary',
    }
    return borderColors[type] || 'border-l-border'
}

function getIconColor(type: FeedActivityType): string {
    const colorMap: Record<FeedActivityType, string> = {
        [FeedActivityType.Dashboard]: 'text-primary',
        [FeedActivityType.EventDefinition]: 'text-success',
        [FeedActivityType.ExperimentLaunched]: 'text-warning',
        [FeedActivityType.ExperimentCompleted]: 'text-success',
        [FeedActivityType.FeatureFlag]: 'text-primary',
        [FeedActivityType.Survey]: 'text-purple',
        [FeedActivityType.ReplayPlaylist]: 'text-danger',
        [FeedActivityType.ExpiringRecordings]: 'text-muted',
        [FeedActivityType.ExternalDataSource]: 'text-primary',
    }
    return colorMap[type] || 'text-muted'
}

function getSummaryText(items: FeedItem[]): string {
    if (items.length <= 3) {
        return items.map((item) => item.title).join(', ')
    }

    // Show first 2 items and count of remaining
    const firstTwo = items.slice(0, 2).map((item) => item.title)
    const remaining = items.length - 2
    return `${firstTwo.join(', ')} and ${remaining} more`
}

export function FeedGroupedCard({ items, type }: FeedGroupedCardProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)

    if (items.length === 0) {
        return <></>
    }

    if (items.length === 1) {
        return <FeedItemThread item={items[0]} />
    }

    return (
        <div className={`border rounded border-l-4 ${getBorderColor(type)} overflow-hidden`}>
            <div
                className="p-4 bg-bg-light hover:bg-accent-primary-highlight cursor-pointer transition-colors"
                onClick={() => setIsExpanded(!isExpanded)}
            >
                <div className="flex items-center justify-between">
                    <div className="flex-1 flex items-center gap-3 min-w-0">
                        <div className={`flex-shrink-0 ${getIconColor(type)}`}>{getActivityIcon(type)}</div>
                        <span className={`font-semibold ${getIconColor(type)} flex-shrink-0`}>
                            {items.length} {getActivityTypeLabel(type, items.length)}
                        </span>
                        <span className="text-muted text-sm truncate">{getSummaryText(items)}</span>
                    </div>
                    <LemonButton
                        size="small"
                        type="tertiary"
                        icon={<IconChevronDown className={isExpanded ? 'rotate-180' : ''} />}
                    />
                </div>
            </div>

            {isExpanded && (
                <div className="border-t border-border">
                    <div className="p-4 space-y-4 bg-bg-3000">
                        {items.map((item) => (
                            <FeedItemThread key={item.id} item={item} />
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}
