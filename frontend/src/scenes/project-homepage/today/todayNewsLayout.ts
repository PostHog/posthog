import type { NewsChartApi, NewsLeadStoryApi } from 'products/today/frontend/generated/api.schemas'

export function leadChart(lead: NewsLeadStoryApi): NewsChartApi | null {
    return lead.chart && lead.chart.kind !== 'line' ? lead.chart : null
}

export function leadHasChart(lead: NewsLeadStoryApi): boolean {
    return !!leadChart(lead) || lead.series.length > 1
}

export function storiesUnderLead<T>(
    stories: T[],
    leadHasChart: boolean,
    ongoingCount: number,
    hasBriefs: boolean
): T[] {
    if (ongoingCount === 0) {
        return []
    }
    const railHeight = ongoingCount * 1.2 + (hasBriefs ? 0.8 : 0)
    let leftHeight = leadHasChart ? 3 : 2
    let count = 0
    while (count < stories.length && leftHeight < railHeight) {
        leftHeight += 1.3
        count += 1
    }
    return stories.length - count === 1 ? stories : stories.slice(0, count)
}
