import {
    IconClock,
    IconComment,
    IconDashboard,
    IconDatabase,
    IconFlag,
    IconFlask,
    IconGraph,
    IconRewindPlay,
} from '@posthog/icons'

import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import { FeedActivityType, FeedItem } from '~/types'

interface FeedItemCardProps {
    item: FeedItem
}

function getActivityIcon(type: FeedActivityType): JSX.Element {
    const iconMap: Record<FeedActivityType, JSX.Element> = {
        [FeedActivityType.Dashboard]: <IconDashboard className="text-primary" />,
        [FeedActivityType.EventDefinition]: <IconGraph className="text-success" />,
        [FeedActivityType.ExperimentLaunched]: <IconFlask className="text-warning" />,
        [FeedActivityType.ExperimentCompleted]: <IconFlask className="text-success" />,
        [FeedActivityType.FeatureFlag]: <IconFlag className="text-primary" />,
        [FeedActivityType.Survey]: <IconComment className="text-purple" />,
        [FeedActivityType.ReplayPlaylist]: <IconRewindPlay className="text-danger" />,
        [FeedActivityType.ExpiringRecordings]: <IconClock className="text-muted" />,
        [FeedActivityType.ExternalDataSource]: <IconDatabase className="text-primary" />,
    }
    return iconMap[type] || <IconGraph />
}

function getActivityTypeLabel(type: FeedActivityType): string {
    const labels: Record<FeedActivityType, string> = {
        [FeedActivityType.Dashboard]: 'Dashboard',
        [FeedActivityType.EventDefinition]: 'Event',
        [FeedActivityType.ExperimentLaunched]: 'Experiment',
        [FeedActivityType.ExperimentCompleted]: 'Experiment',
        [FeedActivityType.ExternalDataSource]: 'Data source',
        [FeedActivityType.FeatureFlag]: 'Feature flag',
        [FeedActivityType.Survey]: 'Survey',
        [FeedActivityType.ReplayPlaylist]: 'Replay playlist',
        [FeedActivityType.ExpiringRecordings]: 'Recording',
    }
    return labels[type] || type
}

function getBorderColor(type: FeedActivityType): string {
    const borderColors: Record<FeedActivityType, string> = {
        [FeedActivityType.Dashboard]: 'border-l-4 border-l-primary',
        [FeedActivityType.EventDefinition]: 'border-l-4 border-l-success',
        [FeedActivityType.ExperimentLaunched]: 'border-l-4 border-l-warning',
        [FeedActivityType.ExperimentCompleted]: 'border-l-4 border-l-success',
        [FeedActivityType.FeatureFlag]: 'border-l-4 border-l-primary',
        [FeedActivityType.Survey]: 'border-l-4 border-l-purple',
        [FeedActivityType.ReplayPlaylist]: 'border-l-4 border-l-danger',
        [FeedActivityType.ExpiringRecordings]: 'border-l-4 border-l-muted',
        [FeedActivityType.ExternalDataSource]: 'border-l-4 border-l-primary',
    }
    return borderColors[type] || 'border-l-4 border-l-border'
}

export function FeedItemCard({ item }: FeedItemCardProps): JSX.Element {
    return (
        <div
            className={`border rounded p-4 hover:bg-accent-primary-highlight transition-colors cursor-pointer ${getBorderColor(item.type)}`}
        >
            <Link to={item.url} className="block">
                <div className="flex items-start gap-3">
                    <div className="flex-shrink-0 mt-1">{getActivityIcon(item.type)}</div>

                    <div className="flex-1 min-w-0">
                        <div className="font-semibold text-default">{item.title}</div>

                        {item.description && <div className="text-muted text-sm mt-1">{item.description}</div>}

                        <div className="flex items-center gap-3 mt-2 text-xs text-muted">
                            {item.creator && (
                                <div className="flex items-center gap-1">
                                    <ProfilePicture size="xs" name={item.creator.name} />
                                    <span>{item.creator.name}</span>
                                </div>
                            )}
                            <TZLabel time={item.created_at} />
                            <span className="text-border">•</span>
                            <span>{getActivityTypeLabel(item.type)}</span>
                        </div>
                    </div>
                </div>
            </Link>
        </div>
    )
}
