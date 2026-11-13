import { useActions, useValues } from 'kea'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { dateMapping } from 'lib/utils/dateFilters'

import { Query } from '~/queries/Query/Query'
import { DataVisualizationNode } from '~/queries/schema/schema-general'

import { supportOverviewSceneLogic } from '../../scenes/overview/supportOverviewSceneLogic'

// The chart queries need a range start, so the picker leaves out the unbounded option.
const DATE_OPTIONS = dateMapping.filter((option) => option.key !== 'All time')

interface Chart {
    key: string
    title: string
    description: string
    query: DataVisualizationNode
}

export function SupportOverviewCharts(): JSX.Element {
    const { dateFilter, ticketsCreatedQuery, ticketsResolvedQuery, firstResponseTimeQuery, slaAttainmentQuery } =
        useValues(supportOverviewSceneLogic)
    const { setDates } = useActions(supportOverviewSceneLogic)

    const charts: Chart[] = [
        {
            key: 'tickets-created',
            title: 'Tickets created',
            description: 'New tickets per day.',
            query: ticketsCreatedQuery,
        },
        {
            key: 'tickets-resolved',
            title: 'Tickets resolved',
            description: 'Tickets moved to resolved per day.',
            query: ticketsResolvedQuery,
        },
        {
            key: 'first-response-time',
            title: 'Time to first response',
            description: 'Median hours from ticket creation to the first reply, by the day the ticket was created.',
            query: firstResponseTimeQuery,
        },
        {
            key: 'sla-attainment',
            title: 'SLA attainment',
            description: 'Share of replies sent before the SLA deadline, on tickets that have an SLA.',
            query: slaAttainmentQuery,
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="m-0">Trends</h2>
                <DateFilter
                    dateFrom={dateFilter.dateFrom}
                    dateTo={dateFilter.dateTo}
                    onChange={setDates}
                    forceGranularity="day"
                    dateOptions={DATE_OPTIONS}
                />
            </div>
            <div className="grid grid-cols-1 gap-4 @min-[60rem]/main-content:grid-cols-2">
                {charts.map((chart) => (
                    <div key={chart.key} className="flex min-w-0 flex-col" data-attr={`support-overview-${chart.key}`}>
                        <h3 className="mb-1">{chart.title}</h3>
                        <p className="mb-3 text-sm text-secondary">{chart.description}</p>
                        <div className="min-w-0">
                            <Query query={chart.query} uniqueKey={`support-overview-${chart.key}`} readOnly />
                        </div>
                    </div>
                ))}
            </div>
        </div>
    )
}
