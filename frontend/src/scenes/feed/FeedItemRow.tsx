import { TZLabel } from 'lib/components/TZLabel'
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
        case 'external_data_source':
            // Data warehouse tables don't have direct URLs yet
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
    }
    return labels[type] || type
}

export function FeedItemRow({ item, config }: FeedItemRowProps): JSX.Element {
    const url = getItemUrl(item)

    return (
        <div
            className="border rounded border-l-4 overflow-hidden"
            style={{ borderLeftColor: config.borderColor }}
            data-attr={`feed-item-${item.type}`}
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
                <Link to={url} className="block px-4 pb-3" data-attr={`feed-item-click-${item.type}`}>
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
        </div>
    )
}
