import type { MainStreakApi } from '../generated/api.schemas'

interface MainStreakCounterProps {
    streak: MainStreakApi | null
    loading?: boolean
}

export function MainStreakCounter({ streak, loading }: MainStreakCounterProps): JSX.Element {
    if (loading || !streak) {
        return (
            <div className="rounded-lg border p-6 animate-pulse">
                <div className="h-12 w-24 bg-border rounded" />
            </div>
        )
    }

    const isBroken = streak.is_broken_now
    const bgClass = isBroken ? 'bg-danger-highlight border-danger' : 'bg-success-highlight border-success'

    return (
        <div className={`rounded-lg border p-6 ${bgClass}`}>
            <div className="flex items-baseline gap-3">
                <span className={`text-5xl font-bold ${isBroken ? 'text-danger' : 'text-success-dark'}`}>
                    {streak.current_streak_days}
                </span>
                <span className={`text-lg ${isBroken ? 'text-danger' : 'text-success-dark'}`}>
                    {streak.current_streak_days === 1 ? 'day' : 'days'} since last broken main
                </span>
            </div>
            <div className="mt-2 text-sm text-muted">
                {isBroken ? (
                    <span>
                        Broken now
                        {(streak.last_incident_workflows ?? []).length > 0 && (
                            <> &mdash; {(streak.last_incident_workflows ?? []).join(', ')}</>
                        )}
                    </span>
                ) : (
                    <span>Record streak: {streak.record_streak_days} days</span>
                )}
            </div>
        </div>
    )
}
