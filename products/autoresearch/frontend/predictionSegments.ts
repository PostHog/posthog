import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { escapePropertyAsHogQLIdentifier } from '~/queries/utils'
import { PersonPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import type { CohortFiltersApi, PersonFilterApi } from 'products/cohorts/frontend/generated/api.schemas'

/**
 * Probability cut points between the segments. Both sit on a histogram decile boundary,
 * so every histogram bar belongs to exactly one segment.
 */
export const PREDICTION_SEGMENT_THRESHOLDS = { high: 0.6, low: 0.2 } as const

export type PredictionSegmentKey = 'likely' | 'possible' | 'unlikely'

export interface PredictionSegmentDefinition {
    key: PredictionSegmentKey
    label: string
    range: string
    /** Tailwind background class for the segment's card accent and histogram bars. */
    colorClassName: string
}

const { high, low } = PREDICTION_SEGMENT_THRESHOLDS

export const PREDICTION_SEGMENTS: PredictionSegmentDefinition[] = [
    { key: 'likely', label: 'Likely', range: `${high * 100}% and above`, colorClassName: 'bg-success' },
    { key: 'possible', label: 'Possible', range: `${low * 100}% to ${high * 100}%`, colorClassName: 'bg-warning' },
    { key: 'unlikely', label: 'Unlikely', range: `Below ${low * 100}%`, colorClassName: 'bg-muted' },
]

/** People and expected conversions of one segment in the latest scoring run. */
export interface PredictionSegmentStats {
    people: number
    /** The sum of the segment's probabilities: how many of its people the model expects to convert. */
    expectedConversions: number
}

export type PredictionSegmentCounts = Record<PredictionSegmentKey, PredictionSegmentStats>

export function predictionSegmentFor(probability: number): PredictionSegmentDefinition {
    const [likely, possible, unlikely] = PREDICTION_SEGMENTS
    return probability >= high ? likely : probability >= low ? possible : unlikely
}

type SegmentBound = { operator: PropertyOperator.GreaterThanOrEqual | PropertyOperator.LessThan; value: number }

function segmentBounds(key: PredictionSegmentKey): SegmentBound[] {
    switch (key) {
        case 'likely':
            return [{ operator: PropertyOperator.GreaterThanOrEqual, value: high }]
        case 'possible':
            return [
                { operator: PropertyOperator.GreaterThanOrEqual, value: low },
                { operator: PropertyOperator.LessThan, value: high },
            ]
        case 'unlikely':
            return [{ operator: PropertyOperator.LessThan, value: low }]
    }
}

/** A dynamic cohort of the people whose output property puts them in the segment. */
export function predictionSegmentCohortFilters(key: PredictionSegmentKey, property: string): CohortFiltersApi {
    const values: PersonFilterApi[] = segmentBounds(key).map(({ operator, value }) => ({
        type: 'person',
        key: property,
        operator,
        value,
    }))
    return { properties: { type: 'OR', values: [{ type: 'AND', values }] } }
}

/** The persons list, filtered with the same conditions as the segment's cohort. */
export function predictionSegmentPeopleUrl(key: PredictionSegmentKey, property: string): string {
    const properties: PersonPropertyFilter[] = segmentBounds(key).map(({ operator, value }) => ({
        type: PropertyFilterType.Person,
        key: property,
        operator,
        value,
    }))
    const query: DataTableNode = {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.ActorsQuery,
            select: [
                ...defaultDataTableColumns(NodeKind.ActorsQuery),
                `properties.${escapePropertyAsHogQLIdentifier(property)}`,
            ],
            properties,
        },
        full: true,
        propertiesViaUrl: true,
    }
    return combineUrl(urls.persons(), {}, { q: query }).url
}
