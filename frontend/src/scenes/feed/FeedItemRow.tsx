import { useState } from 'react'

import { IconComment, IconThumbsUp } from '@posthog/icons'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { urls } from 'scenes/urls'

import { FeedItem } from './feedLogic'

interface FeedItemRowProps {
    item: FeedItem
    config: {
        title: string
        icon: JSX.Element
        color: string
        borderColor: string
    }
}

function getItemUrl(item: FeedItem): string | undefined {
    switch (item.type) {
        case 'dashboard':
            return urls.dashboard(item.id as number)
        case 'event_definition':
            return urls.eventDefinition(item.id as string)
        case 'experiment_launched':
        case 'experiment_completed':
            return urls.experiment(item.id as number)
        case 'feature_flag':
            return urls.featureFlag(item.id as number)
        case 'survey':
            return urls.survey(item.id as string)
        case 'session_recording_playlist':
            return urls.replayPlaylist(item.id as string)
        case 'expiring_recordings':
            return urls.replay() // Link to replay page
        case 'notification':
            // Try to link to the resource if resource_type and resource_id are available
            if (item.additional_data?.resource_type && item.additional_data?.resource_id) {
                const resourceType = item.additional_data.resource_type
                const resourceId = item.additional_data.resource_id
                switch (resourceType) {
                    case 'dashboard':
                        return urls.dashboard(parseInt(resourceId))
                    case 'event_definition':
                        return urls.eventDefinition(resourceId)
                    case 'experiment':
                        return urls.experiment(parseInt(resourceId))
                    case 'feature_flag':
                        return urls.featureFlag(parseInt(resourceId))
                    case 'survey':
                        return urls.survey(resourceId)
                    case 'session_recording_playlist':
                        return urls.replayPlaylist(resourceId)
                    default:
                        return undefined
                }
            }
            return undefined
        default:
            return undefined
    }
}

function getActivityTypeLabel(type: string): string {
    const labels: Record<string, string> = {
        dashboard: 'Dashboard',
        event_definition: 'Event',
        experiment_launched: 'Experiment',
        experiment_completed: 'Experiment',
        feature_flag: 'Feature flag',
        survey: 'Survey',
        session_recording_playlist: 'Replay playlist',
        external_data_source: 'Data source',
        notification: 'Notification',
        expiring_recordings: 'Warning',
    }
    return labels[type] || type
}

export function FeedItemRow({ item, config }: FeedItemRowProps): JSX.Element {
    const [likes, setLikes] = useState(0)
    const [hasLiked, setHasLiked] = useState(false)
    const [showComments, setShowComments] = useState(false)

    const handleLike = (): void => {
        if (hasLiked) {
            setLikes(likes - 1)
        } else {
            setLikes(likes + 1)
        }
        setHasLiked(!hasLiked)
    }

    const url = getItemUrl(item)

    return (
        <div
            className="relative bg-bg-light border border-border rounded hover:border-border-bold transition-all shadow-sm hover:shadow-md border-l-4"
            style={{ borderLeftColor: config.borderColor }}
        >
            {/* Header - Single line with all metadata */}
            <div className="px-4 pt-3 pb-2">
                <div className="flex items-center gap-2 text-xs">
                    <div className="flex-shrink-0">
                        {item.created_by ? (
                            <ProfilePicture size="xs" name={item.created_by} />
                        ) : (
                            <div style={{ color: config.color }}>{config.icon}</div>
                        )}
                    </div>
                    {item.created_by ? (
                        <>
                            <span className="text-muted">Created by</span>
                            <span className="font-medium">{item.created_by}</span>
                        </>
                    ) : (
                        <span className="font-medium">PostHog</span>
                    )}
                    <span className="text-muted">•</span>
                    <span className="text-muted">{getActivityTypeLabel(item.type)}</span>
                    <span className="text-muted">•</span>
                    <TZLabel time={item.created_at} className="text-muted" />
                </div>
            </div>

            {/* Content */}
            {url ? (
                <Link to={url} className="block px-4 pb-3">
                    <div>
                        <h3 className="font-semibold text-base mb-1">{item.name}</h3>
                        {item.description && <p className="text-sm text-muted mb-0">{item.description}</p>}
                    </div>
                </Link>
            ) : (
                <div className="px-4 pb-3">
                    <h3 className="font-semibold text-base mb-1">{item.name}</h3>
                    {item.description && <p className="text-sm text-muted mb-0">{item.description}</p>}
                </div>
            )}

            {/* Interaction Bar */}
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
                    Comment
                </LemonButton>
            </div>

            {/* Comments Section - Placeholder for now */}
            {showComments && (
                <div className="px-4 pb-3 border-t border-border pt-3">
                    <p className="text-xs text-muted italic">Comments coming soon...</p>
                </div>
            )}
        </div>
    )
}
