import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { BetsPage } from '../BetsPage'
import { BetsFilters } from '../components/BetsFilters'
import { BetsTable } from '../components/BetsTable'
import { BetsTableSkeleton } from '../components/BetsTableSkeleton'
import { betsLogic } from '../logics/betsLogic'

export const scene: SceneExport = { component: AllBetsScene, logic: betsLogic }

export function AllBetsScene(): JSX.Element {
    const { overview, overviewLoading, filteredBets, error, breadcrumbs } = useValues(betsLogic)
    const { loadOverview } = useActions(betsLogic)
    return (
        <BetsPage
            title="All bets"
            breadcrumbs={breadcrumbs}
            actions={
                overview?.can_edit && (
                    <Button variant="primary" size="sm" render={<LinkPrimitive to={urls.betsNew()} />}>
                        <IconPlus /> New bet
                    </Button>
                )
            }
        >
            {error ? (
                <div className="flex flex-col items-start gap-3 py-10" role="alert">
                    <Text>{error}</Text>
                    <Button variant="outline" loading={overviewLoading} onClick={() => loadOverview()}>
                        Try again
                    </Button>
                </div>
            ) : !overview ? (
                <div className="mt-8">
                    <BetsFilters />
                    <BetsTableSkeleton />
                </div>
            ) : overview.bets.length ? (
                <div className="mt-8" aria-busy={overviewLoading}>
                    <BetsFilters />
                    {filteredBets.length ? (
                        <BetsTable bets={filteredBets} />
                    ) : (
                        <div className="flex flex-col items-start gap-3 py-10">
                            <Text variant="muted">No bets match these filters.</Text>
                        </div>
                    )}
                </div>
            ) : (
                <div className="flex flex-col items-start gap-3 py-10">
                    <h2 className="Bets__sectionTitle">What should improve next?</h2>
                    <Text variant="muted">Define an outcome, choose a primary metric, and give the bet a budget.</Text>
                    {overview.can_edit && (
                        <Button
                            variant="outline"
                            render={
                                <LinkPrimitive
                                    to={overview.settings.budget_cents ? urls.betsNew() : urls.betsSettings()}
                                />
                            }
                        >
                            {overview.settings.budget_cents ? 'Create your first bet' : 'Set your budget'}
                        </Button>
                    )}
                </div>
            )}
        </BetsPage>
    )
}
