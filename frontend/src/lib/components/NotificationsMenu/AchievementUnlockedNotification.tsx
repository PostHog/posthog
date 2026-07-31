import { WebAnalyticsAchievementMetadata } from '~/types'

function StagePips({ stage, totalStages }: { stage: number; totalStages: number }): JSX.Element | null {
    if (totalStages <= 0) {
        return null
    }
    return (
        <span className="inline-flex items-center gap-0.5" aria-hidden>
            {Array.from({ length: totalStages }, (_, index) => (
                <span
                    key={index}
                    className={`size-1.5 rounded-full ${index < stage ? 'bg-warning' : 'bg-fill-highlight-200'}`}
                />
            ))}
        </span>
    )
}

export function AchievementUnlockedNotification({
    metadata,
}: {
    metadata: WebAnalyticsAchievementMetadata
}): JSX.Element {
    const { stage_name, track_name, stage, total_stages } = metadata
    return (
        <div className="mt-2 flex flex-col gap-1.5">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <span className="text-sm font-bold leading-none">{stage_name}</span>
                <span className="text-xs text-secondary">on the {track_name.toLowerCase()} track</span>
            </div>
            <div className="flex items-center gap-1.5 text-xs text-secondary">
                <StagePips stage={stage} totalStages={total_stages} />
                <span>
                    Stage {stage} of {total_stages} in Web analytics
                </span>
            </div>
        </div>
    )
}
