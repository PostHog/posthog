import { BIConfig } from '~/queries/schema/schema-business-intelligence'

import { getBIResultDimensions } from './biEditorTypes'

export interface BIDashboardFilterLink {
    dashboardId: number
    tileId: number
    record: Record<string, string | number | boolean | null>
}

export function readBIDashboardFilterLink(value: unknown): BIDashboardFilterLink | null {
    try {
        const parsed = typeof value === 'string' ? JSON.parse(value) : value
        if (!parsed || typeof parsed !== 'object') {
            return null
        }
        const { dashboardId, tileId, record } = parsed as Record<string, unknown>
        if (
            typeof dashboardId !== 'number' ||
            !Number.isSafeInteger(dashboardId) ||
            typeof tileId !== 'number' ||
            !Number.isSafeInteger(tileId) ||
            !record ||
            Array.isArray(record) ||
            typeof record !== 'object' ||
            !Object.values(record).every(
                (value) => value === null || ['string', 'number', 'boolean'].includes(typeof value)
            )
        ) {
            return null
        }
        return { dashboardId, tileId, record: record as BIDashboardFilterLink['record'] }
    } catch {
        return null
    }
}

export function getBIDashboardFilterLink(
    currentUrl: string,
    dashboardId: number,
    tileId: number,
    config: BIConfig,
    record: Record<string, unknown>,
    remove = false
): string {
    const url = new URL(currentUrl)
    const hash = new URLSearchParams(url.hash.slice(1))
    hash.delete('insight_filter')
    if (remove) {
        hash.delete('bi_filter')
        return `${url.pathname}${url.search}#${hash}`
    }
    const columns = [...getBIResultDimensions(config).map(({ column }) => column), 'bi_comparison']
    hash.set(
        'bi_filter',
        JSON.stringify({
            dashboardId,
            tileId,
            record: Object.fromEntries(
                columns.filter((column) => column in record).map((column) => [column, record[column]])
            ),
        })
    )
    return `${url.pathname}${url.search}#${hash}`
}
