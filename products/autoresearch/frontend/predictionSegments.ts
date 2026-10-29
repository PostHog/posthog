import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { escapePropertyAsHogQLIdentifier } from '~/queries/utils'
import { BaseMathType, PersonPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import type { CohortFiltersApi, PersonFilterApi } from 'products/cohorts/frontend/generated/api.schemas'
import { urlForNewWorkflowWithTrigger } from 'products/workflows/frontend/Workflows/workflowTriggerPrefill'

import type { AutoresearchPipelineApi, PredictionSegmentThresholdsApi } from './generated/api.schemas'

/**
 * The cut points come from the online_performance endpoint: lift over the model's realized base rate,
 * or a fixed pair until enough predictions are checked. Online validation counts its Likely flags
 * with the same cut point.
 */
export type PredictionSegmentThresholds = Pick<
    PredictionSegmentThresholdsApi,
    'likely_threshold' | 'possible_threshold' | 'base_rate'
>

export type PredictionSegmentKey = 'likely' | 'possible' | 'unlikely'

export const PREDICTION_SEGMENT_KEYS: PredictionSegmentKey[] = ['likely', 'possible', 'unlikely']

export interface PredictionSegmentDefinition {
    key: PredictionSegmentKey
    label: string
    /** The range as the cards show it, relative to the average when there is a base rate. */
    range: string
    /** The range in probabilities only. Saved cohorts keep this cut point, so their names state it. */
    probabilityRange: string
    /** Tailwind background class for the segment's card accent and histogram bars. */
    colorClassName: string
}

/** A probability as a percentage with up to three significant digits, so a rare target's 0.045 reads 4.5%. */
export function formatProbability(probability: number): string {
    return `${parseFloat((probability * 100).toPrecision(3))}%`
}

function formatLift(lift: number): string {
    return `${parseFloat(lift.toFixed(1))}×`
}

export function predictionSegmentDefinitions({
    likely_threshold: high,
    possible_threshold: low,
    base_rate: baseRate,
}: PredictionSegmentThresholds): PredictionSegmentDefinition[] {
    const highText = formatProbability(high)
    const lowText = formatProbability(low)
    const probabilityRanges: Record<PredictionSegmentKey, string> = {
        likely: `${highText} and above`,
        possible: `${lowText} to ${highText}`,
        unlikely: `Below ${lowText}`,
    }
    // A high base rate caps the Likely cut point, so the lift is read off the cut point, not the configured one.
    const lift = baseRate ? formatLift(high / baseRate) : null
    const ranges: Record<PredictionSegmentKey, string> = lift
        ? {
              likely: `${lift} average or higher (${highText}+)`,
              possible: `Average to ${lift} (${lowText} to ${highText})`,
              unlikely: `Below average (under ${lowText})`,
          }
        : probabilityRanges
    return [
        {
            key: 'likely',
            label: 'Likely',
            range: ranges.likely,
            probabilityRange: probabilityRanges.likely,
            colorClassName: 'bg-success',
        },
        {
            key: 'possible',
            label: 'Possible',
            range: ranges.possible,
            probabilityRange: probabilityRanges.possible,
            colorClassName: 'bg-warning',
        },
        {
            key: 'unlikely',
            label: 'Unlikely',
            range: ranges.unlikely,
            probabilityRange: probabilityRanges.unlikely,
            colorClassName: 'bg-muted',
        },
    ]
}

/** People and expected conversions of one segment in the latest scoring run. */
export interface PredictionSegmentStats {
    people: number
    /** The sum of the segment's probabilities: how many of its people the model expects to convert. */
    expectedConversions: number
}

export type PredictionSegmentCounts = Record<PredictionSegmentKey, PredictionSegmentStats>

function segmentKeyFor(probability: number, thresholds: PredictionSegmentThresholds): PredictionSegmentKey {
    return probability >= thresholds.likely_threshold
        ? 'likely'
        : probability >= thresholds.possible_threshold
          ? 'possible'
          : 'unlikely'
}

export function predictionSegmentFor(
    probability: number,
    thresholds: PredictionSegmentThresholds
): PredictionSegmentDefinition {
    const key = segmentKeyFor(probability, thresholds)
    return predictionSegmentDefinitions(thresholds).find(
        (segment) => segment.key === key
    ) as PredictionSegmentDefinition
}

/** The segment of every score in [lower, upper), or null when a cut point splits the range. */
export function predictionSegmentForRange(
    lower: number,
    upper: number,
    thresholds: PredictionSegmentThresholds
): PredictionSegmentDefinition | null {
    const split = [thresholds.likely_threshold, thresholds.possible_threshold].some(
        (cutPoint) => cutPoint > lower && cutPoint < upper
    )
    return split ? null : predictionSegmentFor(lower, thresholds)
}

type SegmentBound = { operator: PropertyOperator.GreaterThanOrEqual | PropertyOperator.LessThan; value: number }

function segmentBounds(
    key: PredictionSegmentKey,
    { likely_threshold: high, possible_threshold: low }: PredictionSegmentThresholds
): SegmentBound[] {
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
export function predictionSegmentCohortFilters(
    key: PredictionSegmentKey,
    property: string,
    thresholds: PredictionSegmentThresholds
): CohortFiltersApi {
    const values: PersonFilterApi[] = segmentBounds(key, thresholds).map(({ operator, value }) => ({
        type: 'person',
        key: property,
        operator,
        value,
    }))
    return { properties: { type: 'OR', values: [{ type: 'AND', values }] } }
}

function segmentPropertyFilters(
    key: PredictionSegmentKey,
    property: string,
    thresholds: PredictionSegmentThresholds
): PersonPropertyFilter[] {
    return segmentBounds(key, thresholds).map(({ operator, value }) => ({
        type: PropertyFilterType.Person,
        key: property,
        operator,
        value,
    }))
}

/** The persons list, filtered with the same conditions as the segment's cohort. */
export function predictionSegmentPeopleUrl(
    key: PredictionSegmentKey,
    property: string,
    thresholds: PredictionSegmentThresholds
): string {
    const properties = segmentPropertyFilters(key, property, thresholds)
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

export type PredictionLinkDestination = 'feature_flag' | 'workflow' | 'insight'

/** A new feature flag released to the likely segment. */
export function likelySegmentFeatureFlagUrl(property: string, thresholds: PredictionSegmentThresholds): string {
    return urls.featureFlagNew({ properties: segmentPropertyFilters('likely', property, thresholds) })
}

/** A new batch workflow whose audience is the likely segment. */
export function likelySegmentWorkflowUrl(property: string, thresholds: PredictionSegmentThresholds): string {
    return urlForNewWorkflowWithTrigger({
        type: 'batch',
        filters: { properties: segmentPropertyFilters('likely', property, thresholds) },
    })
}

/** A new trends insight of the people who did the target, broken down by their predicted probability. */
export function predictionBreakdownInsightUrl(
    { target_definition: target, target_event: event }: AutoresearchPipelineApi,
    property: string
): string {
    const query: InsightVizNode = {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [
                target.type === 'action'
                    ? { kind: NodeKind.ActionsNode, id: target.action_id, math: BaseMathType.UniqueUsers }
                    : { kind: NodeKind.EventsNode, event, name: event, math: BaseMathType.UniqueUsers },
            ],
            breakdownFilter: {
                breakdown: property,
                breakdown_type: 'person',
                breakdown_histogram_bin_count: 10,
            },
        },
    }
    return urls.insightNew({ query })
}
