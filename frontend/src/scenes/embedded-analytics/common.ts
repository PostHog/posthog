import { PostHogComDocsURL } from 'lib/lemon-ui/Link/Link'

import { QuerySchema } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

export interface EmbeddedTileLayout {
    /** The class has to be spelled out without interpolation, as otherwise Tailwind can't pick it up. */
    colSpanClassName?: `md:col-span-${number}` | 'md:col-span-full'
    /** The class has to be spelled out without interpolation, as otherwise Tailwind can't pick it up. */
    rowSpanClassName?: `md:row-span-${number}`
    /** The class has to be spelled out without interpolation, as otherwise Tailwind can't pick it up. */
    orderWhenLargeClassName?: `xxl:order-${number}`
    className?: string
}

export enum EmbeddedAnalyticsTileId {
    API_QUERIES_COUNT = 'API_QUERIES_COUNT',
}

export const loadPriorityMap: Record<EmbeddedAnalyticsTileId, number> = {
    [EmbeddedAnalyticsTileId.API_QUERIES_COUNT]: 1,
}

export interface EmbeddedBaseTile {
    tileId: EmbeddedAnalyticsTileId
    layout: EmbeddedTileLayout
    docs?: EmbeddedDocs
}

export interface EmbeddedDocs {
    url?: PostHogComDocsURL
    title: string
    description: string | JSX.Element
}

export interface EmbeddedQueryTile extends EmbeddedBaseTile {
    kind: 'query'
    title?: string
    query: QuerySchema
    showIntervalSelect?: boolean
    control?: JSX.Element
    insightProps: InsightLogicProps
    canOpenModal?: boolean
    canOpenInsight?: boolean
}

export type EmbeddedAnalyticsTile = EmbeddedQueryTile
