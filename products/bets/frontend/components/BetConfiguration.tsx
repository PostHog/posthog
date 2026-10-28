import { urls } from 'scenes/urls'

import type { BetsDetailApi } from '../generated/api.schemas'
import { BetResourceLink } from './BetResourceLink'

export function BetConfiguration({
    bet,
}: {
    bet: Pick<BetsDetailApi, 'repository' | 'work' | 'goal_version' | 'scout' | 'state'>
}): JSX.Element {
    const experiments = bet.work.filter((item) => item.experiment_id !== null && item.goal_version === bet.goal_version)
    return (
        <section className="Bets__details flex min-w-0 flex-col gap-2.5" aria-label="Connected">
            <h2 className="Bets__sectionTitle">Connected</h2>
            <div className="Bets__detailsList">
                {bet.repository ? (
                    <BetResourceLink
                        kind="repository"
                        title={bet.repository}
                        detail="Repository"
                        href={`https://github.com/${bet.repository}`}
                    />
                ) : (
                    <BetResourceLink kind="repository" title="No repository" detail="Not connected" href="" disabled />
                )}
                {bet.scout && (
                    <BetResourceLink
                        kind="scout"
                        title="Scout"
                        href={urls.inboxScout(bet.scout.name)}
                        detail={bet.state.scout.label}
                    />
                )}
                {experiments.map((item) => (
                    <BetResourceLink
                        key={item.id}
                        kind="experiment"
                        title={item.title}
                        detail="Experiment"
                        href={urls.experiment(item.experiment_id!)}
                        id={String(item.experiment_id)}
                    />
                ))}
            </div>
        </section>
    )
}
