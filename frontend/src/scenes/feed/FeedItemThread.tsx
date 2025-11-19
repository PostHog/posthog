import { useState } from 'react'

import {
    IconClock,
    IconComment,
    IconDashboard,
    IconDatabase,
    IconFlag,
    IconFlask,
    IconGraph,
    IconRewindPlay,
    IconThumbsUp,
} from '@posthog/icons'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import { FeedActivityType, FeedItem } from '~/types'

import { FeedComments } from './FeedComments'

interface FeedItemThreadProps {
    item: FeedItem
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

function getActivityColor(type: FeedActivityType): string {
    const colorMap: Record<FeedActivityType, string> = {
        [FeedActivityType.Dashboard]: 'border-primary',
        [FeedActivityType.EventDefinition]: 'border-success',
        [FeedActivityType.ExperimentLaunched]: 'border-warning',
        [FeedActivityType.ExperimentCompleted]: 'border-success',
        [FeedActivityType.FeatureFlag]: 'border-primary',
        [FeedActivityType.Survey]: 'border-purple',
        [FeedActivityType.ReplayPlaylist]: 'border-danger',
        [FeedActivityType.ExpiringRecordings]: 'border-muted',
        [FeedActivityType.ExternalDataSource]: 'border-primary',
    }
    return colorMap[type] || 'border-border'
}

function getActivityIconColor(type: FeedActivityType): string {
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

function getMetadataKey(type: FeedActivityType): string {
    const keyMap: Record<FeedActivityType, string> = {
        [FeedActivityType.Dashboard]: 'dashboard_id',
        [FeedActivityType.EventDefinition]: 'event_definition_id',
        [FeedActivityType.ExperimentLaunched]: 'experiment_id',
        [FeedActivityType.ExperimentCompleted]: 'experiment_id',
        [FeedActivityType.FeatureFlag]: 'feature_flag_id',
        [FeedActivityType.Survey]: 'survey_id',
        [FeedActivityType.ReplayPlaylist]: 'replay_playlist_id',
        [FeedActivityType.ExpiringRecordings]: 'recording_id',
        [FeedActivityType.ExternalDataSource]: 'external_data_source_id',
    }
    return keyMap[type] || `${type}_id`
}

export function FeedItemThread({ item }: FeedItemThreadProps): JSX.Element {
    const [showComments, setShowComments] = useState(false)
    const [likes, setLikes] = useState(0)
    const [hasLiked, setHasLiked] = useState(false)

    const handleLike = (): void => {
        if (hasLiked) {
            setLikes(likes - 1)
        } else {
            setLikes(likes + 1)
        }
        setHasLiked(!hasLiked)
    }

    return (
        <div
            className={`relative bg-bg-light border border-border rounded hover:border-border-bold transition-all shadow-sm hover:shadow-md ${getActivityColor(item.type)} border-l-4`}
        >
            {/* Header - Single line with all metadata */}
            <div className="px-4 pt-3 pb-2">
                <div className="flex items-center gap-2 text-xs">
                    <div className="flex-shrink-0">
                        {item.creator ? (
                            <ProfilePicture size="xs" name={item.creator.name} />
                        ) : (
                            <div className={`${getActivityIconColor(item.type)}`}>{getActivityIcon(item.type)}</div>
                        )}
                    </div>
                    <span className="font-medium">{item.creator ? item.creator.name : 'PostHog'}</span>
                    <span className="text-muted">•</span>
                    <span className="text-muted">{getActivityTypeLabel(item.type)}</span>
                    <span className="text-muted">•</span>
                    <TZLabel time={item.created_at} className="text-muted" />
                </div>
            </div>

            {/* Content */}
            <Link to={item.url} className="block px-4 pb-3">
                <div>
                    <h3 className="font-semibold text-base mb-1">{item.title}</h3>
                    {item.description && <p className="text-sm text-muted mb-2">{item.description}</p>}
                    {Object.keys(item.metadata).length > 0 && (
                        <div className="flex gap-3 text-xs text-muted">
                            {item.metadata.view_count && <span>{item.metadata.view_count} views</span>}
                            {item.metadata.recording_count && <span>{item.metadata.recording_count} recordings</span>}
                        </div>
                    )}
                </div>
            </Link>

            {/* Interaction Bar - Subtle */}
            <div className="px-4 pb-2 flex items-center gap-1 text-xs border-t border-border pt-2">
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={<IconThumbsUp />}
                    onClick={handleLike}
                    className={hasLiked ? 'text-primary' : ''}
                >
                    {likes > 0 ? likes : null}
                </LemonButton>

                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={<IconComment />}
                    onClick={() => setShowComments(!showComments)}
                >
                    {showComments ? 'Hide' : 'Comment'}
                </LemonButton>
            </div>

            {/* Comments Section */}
            {showComments && (
                <div className="px-4 pb-3 border-t border-border pt-3">
                    <FeedComments scope={item.type} itemId={item.metadata[getMetadataKey(item.type)] || item.id} />
                </div>
            )}
        </div>
    )
}
