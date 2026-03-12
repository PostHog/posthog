import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { BreakdownFilter, EventsNode, NodeKind, TrendsFilter } from '~/queries/schema/schema-general'
import { ChartDisplayType, InsightLogicProps } from '~/types'

import { HARNESS_INSIGHT_ID } from './InsightHarness'

function getLogic(): ReturnType<typeof insightVizDataLogic.build> {
    const props: InsightLogicProps = { dashboardItemId: HARNESS_INSIGHT_ID }
    return insightVizDataLogic(props)
}

export const series = {
    set(events: Array<{ event: string; name?: string; math?: string }>): void {
        getLogic().actions.updateQuerySource({
            series: events.map((e) => ({
                kind: NodeKind.EventsNode,
                event: e.event,
                name: e.name ?? e.event,
                ...(e.math ? { math: e.math } : {}),
            })),
        })
    },

    add(event: string, options?: { name?: string; math?: string }): void {
        const current = getLogic().values.querySource
        const existing = (current as any)?.series ?? []
        getLogic().actions.updateQuerySource({
            series: [
                ...existing,
                {
                    kind: NodeKind.EventsNode,
                    event,
                    name: options?.name ?? event,
                    ...(options?.math ? { math: options.math } : {}),
                } as EventsNode,
            ],
        })
    },

    remove(index: number): void {
        const current = getLogic().values.querySource
        const existing = [...((current as any)?.series ?? [])]
        existing.splice(index, 1)
        getLogic().actions.updateQuerySource({ series: existing })
    },
}

export const breakdown = {
    set(property: string, type: BreakdownFilter['breakdown_type'] = 'event'): void {
        const current = (getLogic().values.querySource as any)?.breakdownFilter ?? {}
        getLogic().actions.updateQuerySource({
            breakdownFilter: { ...current, breakdown_type: type, breakdown: property },
        })
    },

    clear(): void {
        getLogic().actions.updateQuerySource({
            breakdownFilter: { breakdown: undefined, breakdown_type: undefined, breakdowns: undefined },
        })
    },
}

export const interval = {
    set(value: 'minute' | 'hour' | 'day' | 'week' | 'month'): void {
        getLogic().actions.updateQuerySource({ interval: value })
    },
}

export const dateRange = {
    set(from: string, to?: string | null): void {
        const current = (getLogic().values.querySource as any)?.dateRange ?? {}
        getLogic().actions.updateQuerySource({
            dateRange: { ...current, date_from: from, date_to: to ?? undefined },
        })
    },

    last(n: number, unit: 'h' | 'd' | 'w' | 'm' = 'd'): void {
        getLogic().actions.updateQuerySource({
            dateRange: { date_from: `-${n}${unit}`, date_to: undefined },
        })
    },
}

export const display = {
    set(type: ChartDisplayType): void {
        const current = (getLogic().values.querySource as any)?.trendsFilter ?? {}
        getLogic().actions.updateQuerySource({
            trendsFilter: { ...current, display: type },
        })
    },
}

export const compare = {
    enable(options?: { compareTo?: string }): void {
        const current = (getLogic().values.querySource as any)?.compareFilter ?? {}
        getLogic().actions.updateQuerySource({
            compareFilter: { ...current, compare: true, compare_to: options?.compareTo },
        })
    },

    disable(): void {
        getLogic().actions.updateQuerySource({
            compareFilter: { compare: false },
        })
    },
}

export const filter = {
    update(insightFilter: Partial<TrendsFilter>): void {
        const current = (getLogic().values.querySource as any)?.trendsFilter ?? {}
        getLogic().actions.updateQuerySource({
            trendsFilter: { ...current, ...insightFilter },
        })
    },

    setTestAccountsFilter(enabled: boolean): void {
        getLogic().actions.updateQuerySource({ filterTestAccounts: enabled })
    },
}

export function getQuerySource(): any {
    return getLogic().values.querySource
}
