import { Text } from '@posthog/quill'

import type { BetsDetailApi } from '../generated/api.schemas'
import { isBuilt, waitingIdeas } from '../lib/ideas'
import { isOpen } from '../lib/workStatus'
import { BetWorkRow } from './BetWorkRow'

export function BetProgress({ bet }: { bet: BetsDetailApi }): JSX.Element {
    const current = bet.work.filter((item) => isBuilt(item) && (item.goal_version === bet.goal_version || isOpen(item)))
    const open = current.filter(isOpen)
    const finished = current.filter((item) => !isOpen(item))
    return (
        <section className="mt-6" aria-label="Progress">
            <h2 className="Bets__sectionTitle">Progress</h2>
            {!current.length ? (
                <Text size="sm" variant="muted" render={<p className="mt-4" />}>
                    {waitingIdeas(bet).length
                        ? 'Nothing is built yet. Choose an idea above to start.'
                        : 'Bets is getting started. The first step checks how the goal is measured.'}
                </Text>
            ) : (
                <div className="mt-2">
                    {[...open, ...finished].map((item) => (
                        <BetWorkRow key={item.id} item={item} bet={bet} />
                    ))}
                </div>
            )}
        </section>
    )
}
