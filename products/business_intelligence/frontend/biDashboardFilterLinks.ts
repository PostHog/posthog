import { z } from 'zod'

import { BIConfig } from '~/queries/schema/schema-business-intelligence'

import { getBIResultDimensions } from './biEditorTypes'

const filterLinkSchema = z.object({
    dashboardId: z.number().int().safe(),
    tileId: z.number().int().safe(),
    record: z.record(z.string(), z.union([z.string(), z.number(), z.boolean(), z.null()])),
})

export type BIDashboardFilterLink = z.infer<typeof filterLinkSchema>

export function readBIDashboardFilterLink(value: unknown): BIDashboardFilterLink | null {
    try {
        const result = filterLinkSchema.safeParse(typeof value === 'string' ? JSON.parse(value) : value)
        return result.success ? result.data : null
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
