import { IconTarget } from '@posthog/icons'
import { LemonCard } from 'lib/lemon-ui/LemonCard'

export const BetDefinitionsContent = (): JSX.Element => (
    <div className="mt-4">
        <h3 className="mb-4">Available Bets</h3>
        <LemonCard className="p-6">
            <div className="text-center">
                <IconTarget className="text-4xl mb-4 text-primary" />
                <h3 className="text-lg font-semibold">Coming Soon</h3>
                <p className="text-muted mt-2">
                    Bet definitions will be available soon. Check back later to place bets on metrics.
                </p>
            </div>
        </LemonCard>
    </div>
)
