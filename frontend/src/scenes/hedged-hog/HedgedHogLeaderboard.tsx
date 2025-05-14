import { IconCrown } from '@posthog/icons'
import { LemonCard } from 'lib/lemon-ui/LemonCard'

export const LeaderboardContent = (): JSX.Element => (
    <div className="mt-4">
        <h3 className="mb-4">Leaderboard</h3>
        <LemonCard className="p-6">
            <div className="text-center">
                <IconCrown className="text-4xl mb-4 text-warning" />
                <h3 className="text-lg font-semibold">Coming Soon</h3>
                <p className="text-muted mt-2">
                    The leaderboard will be available soon. Check back later to see how you rank against other players.
                </p>
            </div>
        </LemonCard>
    </div>
)
