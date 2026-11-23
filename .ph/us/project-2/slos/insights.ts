import { hogql, type InsightInput } from '@posthog/sdk/define'

import { tags } from '../shared/teams'
import { burnRateQuery, dailyQueries, type Region, successRateQuery } from './queries'

export interface Slo {
    key: keyof typeof dailyQueries
    namePrefix: string
    description: string
    errorBudget: number
    regions: Region[]
}

export const slos: Slo[] = [
    {
        key: 'alerts',
        namePrefix: 'SLO: Alert checks',
        description: 'Rolling burn rate for alert checks.',
        errorBudget: 0.01,
        regions: ['us', 'eu'],
    },
    {
        key: 'alerts_timeliness',
        namePrefix: 'SLO: Alert timeliness',
        description: 'Rolling burn rate for alert check timeliness.',
        errorBudget: 0.01,
        regions: ['us', 'eu'],
    },
    {
        key: 'exports',
        namePrefix: 'SLO: Exports',
        description: 'Rolling burn rate for exports.',
        errorBudget: 0.01,
        regions: ['us', 'eu'],
    },
    {
        key: 'subscriptions',
        namePrefix: 'SLO: Subscription deliveries',
        description: 'Rolling burn rate for subscription deliveries.',
        errorBudget: 0.01,
        regions: ['us', 'eu'],
    },
    {
        key: 'cohorts',
        namePrefix: 'SLO: Cohort calculations',
        description:
            'Rolling burn rate for cohort calculations. Cohorts not calculated within a day count as failures.',
        errorBudget: 0.01,
        regions: ['us', 'eu'],
    },
]

export interface SloRegion {
    // As `alerts_us`.
    key: string
    slo: Slo
    region: Region
    name: string
    daily: string
}

const byKey = (a: SloRegion, b: SloRegion): number => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0)

// One per SLO and region, in key order, which is the order the combined chart lists them in.
export const sloRegions: SloRegion[] = slos
    .flatMap((slo) =>
        slo.regions.map((region) => ({
            key: `${slo.key}_${region}`,
            slo,
            region,
            name: `${slo.namePrefix} — ${(100 - slo.errorBudget * 100).toFixed(0)}%${slo.regions.length > 1 ? ` (${region.toUpperCase()})` : ''}`,
            daily: dailyQueries[slo.key](region),
        }))
    )
    .sort(byKey)

const plain = { formatting: { prefix: '', suffix: '' } }

export function burnRate({ name, slo, daily }: SloRegion): InsightInput {
    return hogql({
        name,
        description: slo.description,
        tags: [tags.managed, tags.slo],
        query: burnRateQuery(daily, slo.errorBudget),
        display: 'ActionsLineGraph',
        chartSettings: {
            xAxis: { column: 'date' },
            yAxis: [{ column: 'value', settings: plain }],
            seriesBreakdownColumn: 'metric',
            showLegend: true,
        },
        tableSettings: {
            columns: [
                { column: 'date', settings: plain },
                { column: 'metric', settings: plain },
                { column: 'value', settings: plain },
            ],
        },
    })
}

const percent = { formatting: { prefix: '', suffix: '%' } }

export const successRates = hogql({
    name: 'SLO: Success rates',
    description: 'Combined 30-day success rates for all SLOs.',
    tags: [tags.managed, tags.slo],
    query: successRateQuery(sloRegions),
    display: 'ActionsLineGraph',
    chartSettings: {
        xAxis: { column: 'date' },
        yAxis: [{ column: 'value', settings: percent }],
        seriesBreakdownColumn: 'slo',
        showLegend: true,
    },
    tableSettings: {
        columns: [
            { column: 'date', settings: plain },
            { column: 'slo', settings: plain },
            { column: 'value', settings: percent },
        ],
    },
})
