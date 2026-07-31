import { WebAnalyticsAchievementMetadata } from '~/types'

export function AchievementUnlockedNotification({
    metadata,
}: {
    metadata: WebAnalyticsAchievementMetadata
}): JSX.Element {
    const { stage_name, track_name, stage, total_stages } = metadata
    return (
        <div className="mt-2 flex flex-col gap-1">
            <div className="flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
                {/* Matches the row title's weight — the achievement name is the body, not a second heading */}
                <span className="text-xs font-semibold">{stage_name}</span>
                <span className="text-xs text-secondary">on the {track_name.toLowerCase()} track</span>
            </div>
            <div className="text-xs text-secondary">
                Stage {stage} of {total_stages} in Web analytics
            </div>
        </div>
    )
}
