import { ComponentType } from 'react'

import { isNonEmptyObject } from 'lib/utils/guards'

import { isNodeWithSource } from '~/queries/utils'
import { InsightModel } from '~/types'

import { QUERY_TYPES_METADATA } from './insightTypesMetadata'

export function InsightIcon({ insight, className }: { insight: InsightModel; className?: string }): JSX.Element | null {
    let Icon: ComponentType<any> | null = null

    if ('query' in insight && isNonEmptyObject(insight.query)) {
        const insightType = isNodeWithSource(insight.query) ? insight.query.source.kind : insight.query.kind
        const insightMetadata = QUERY_TYPES_METADATA[insightType]
        Icon = insightMetadata && insightMetadata.icon
    }

    return Icon ? <Icon className={className} /> : null
}
