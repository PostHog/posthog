import { useValues } from 'kea'
import { router } from 'kea-router'

import { AnalyticsMetricCard } from 'lib/components/AnalyticsMetricCard/AnalyticsMetricCard'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { SupportOverviewNumberKey, ticketListUrl } from '../../scenes/overview/supportOverviewQueries'
import { supportOverviewSceneLogic } from '../../scenes/overview/supportOverviewSceneLogic'

interface NumberCard {
    key: SupportOverviewNumberKey
    title: string
    subtitle: string
    // pinned: data-attr value, because autocapture dashboards and Playwright selectors depend on it.
    dataAttr: string
    needsSla: boolean
}

const CARDS: NumberCard[] = [
    {
        key: 'open',
        title: 'Open tickets',
        subtitle: 'Not resolved yet',
        dataAttr: 'support-overview-open-tickets',
        needsSla: false,
    },
    {
        key: 'unassigned',
        title: 'Unassigned',
        subtitle: 'No assignee',
        dataAttr: 'support-overview-unassigned-tickets',
        needsSla: false,
    },
    {
        key: 'slaAtRisk',
        title: 'SLA at risk',
        subtitle: 'Due within an hour',
        dataAttr: 'support-overview-sla-at-risk',
        needsSla: true,
    },
    {
        key: 'slaBreached',
        title: 'SLA breached',
        subtitle: 'Past the deadline',
        dataAttr: 'support-overview-sla-breached',
        needsSla: true,
    },
]

export function SupportOverviewNumbers(): JSX.Element {
    const { numbers, numbersLoading, numbersFailed } = useValues(supportOverviewSceneLogic)

    return (
        <div className="grid gap-2 grid-cols-[repeat(auto-fit,minmax(11rem,1fr))]">
            {CARDS.map((card) => {
                const slaUnused = card.needsSla && numbers !== null && numbers.withSla === 0
                const hasValue = numbers !== null && !slaUnused
                return (
                    <AnalyticsMetricCard
                        key={card.key}
                        title={card.title}
                        subtitle={card.subtitle}
                        value={hasValue ? numbers[card.key] : undefined}
                        formatValue={humanFriendlyNumber}
                        loading={numbers === null && numbersLoading}
                        error={numbersFailed ? "Couldn't load this number. Refresh the page to try again." : undefined}
                        emptyMessage="No open ticket has an SLA. Set SLAs with a workflow."
                        onClick={hasValue ? () => router.actions.push(ticketListUrl(card.key)) : undefined}
                        ariaLabel={`${card.title}. Show these tickets.`}
                        dataAttr={card.dataAttr}
                    />
                )
            })}
        </div>
    )
}
