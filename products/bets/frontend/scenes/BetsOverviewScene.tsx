import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { BetsPage } from '../BetsPage'
import { BetsAllocation } from '../components/BetsAllocation'
import { BetsMetric } from '../components/BetsMetric'
import { BetsNextAction } from '../components/BetsNextAction'
import { BetsOverviewSkeleton } from '../components/BetsOverviewSkeleton'
import { betsLogic } from '../logics/betsLogic'

export const scene: SceneExport = { component: BetsOverviewScene, logic: betsLogic }

export function BetsOverviewScene(): JSX.Element {
    const { overview, overviewLoading, error, breadcrumbs } = useValues(betsLogic)
    const { loadOverview } = useActions(betsLogic)
    return (
        <BetsPage
            title="Overview"
            description="Decisions and next steps for your bets."
            breadcrumbs={breadcrumbs}
            actions={
                overview?.can_edit && (
                    <Button variant="primary" size="sm" render={<LinkPrimitive to={urls.betsNew()} />}>
                        <IconPlus /> New bet
                    </Button>
                )
            }
        >
            {overview && !error && (
                <div className="Bets__summary mb-6 py-8">
                    <BetsMetric
                        metric={overview.north_star}
                        label={overview.north_star.name === 'Goal' ? 'North Star' : overview.north_star.name}
                    />
                    <BetsAllocation overview={overview} />
                </div>
            )}
            {error ? (
                <div className="flex flex-col items-start gap-3 py-10" role="alert">
                    <Text>{error}</Text>
                    <Button variant="outline" loading={overviewLoading} onClick={() => loadOverview()}>
                        Try again
                    </Button>
                </div>
            ) : !overview ? (
                <BetsOverviewSkeleton />
            ) : overview.next_actions.length ? (
                <section className="mt-8" aria-label="Needs your attention">
                    <div className="flex items-center gap-2">
                        <h2 className="Bets__sectionTitle">Needs your attention</h2>
                        <Text size="sm" variant="muted">
                            {overview.next_actions.length}
                        </Text>
                    </div>
                    <ul className="mt-5 list-none p-0">
                        {overview.next_actions.map((item) => (
                            <BetsNextAction key={item.id} item={item} />
                        ))}
                    </ul>
                </section>
            ) : (
                <div className="flex flex-col items-start gap-3 py-10">
                    <h2 className="Bets__sectionTitle">
                        {overview.bets.length ? 'Nothing needs your attention' : 'Start with your first bet'}
                    </h2>
                    <Text size="sm" variant="muted">
                        {overview.bets.length
                            ? 'Bets continues routine work automatically. Approval requests and blockers will appear here.'
                            : 'Define what should improve and how you will measure it.'}
                    </Text>
                    <Button
                        variant="outline"
                        render={
                            <LinkPrimitive
                                to={
                                    overview.bets.length || !overview.can_edit
                                        ? urls.betsAll()
                                        : overview.settings.budget_cents
                                          ? urls.betsNew()
                                          : urls.betsSettings()
                                }
                            />
                        }
                    >
                        {overview.bets.length || !overview.can_edit
                            ? 'View all bets'
                            : overview.settings.budget_cents
                              ? 'New bet'
                              : 'Set your budget'}
                    </Button>
                </div>
            )}
        </BetsPage>
    )
}
