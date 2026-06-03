import { NodeKind } from '~/queries/schema/schema-general'
import { PropertyFilterType, SurveyEventName } from '~/types'

type RatingTrendSeries = {
    event: string
    kind: NodeKind.EventsNode
    custom_name: string
    properties: Array<{
        type: PropertyFilterType.HogQL
        key: string
    }>
}

export function createNPSTrendSeries(
    values: string[],
    label: string,
    questionIndex: number,
    questionId?: string
): RatingTrendSeries {
    return {
        event: SurveyEventName.SENT,
        kind: NodeKind.EventsNode,
        custom_name: label,
        properties: [
            {
                type: PropertyFilterType.HogQL,
                // Survey responses are read as strings (getSurveyResponse uses JSONExtractString),
                // so the comparison values must be quoted too. Unquoted numeric literals make
                // ClickHouse infer Float64 and fail with "no supertype for types String, Float64".
                key: `getSurveyResponse(${questionIndex}, ${questionId ? `'${questionId}'` : ''}) in (${values
                    .map((value) => `'${value}'`)
                    .join(',')})`,
            },
        ],
    }
}

export function createSingleRatingTrendSeries(
    ratingValue: string,
    questionIndex: number,
    questionId: string
): RatingTrendSeries {
    return {
        event: SurveyEventName.SENT,
        kind: NodeKind.EventsNode,
        custom_name: `Rating ${ratingValue}`,
        properties: [
            {
                type: PropertyFilterType.HogQL,
                key: `getSurveyResponse(${questionIndex}, '${questionId}') = '${ratingValue}'`,
            },
        ],
    }
}

export const CHART_INSIGHTS_COLORS = [
    '#1D4BFF',
    '#CD0F74',
    '#43827E',
    '#621DA6',
    '#F04F58',
    '#539B0A',
    '#E3A605',
    '#0476FB',
    '#36416B',
    '#41CBC3',
    '#A46FFF',
    '#FE729E',
    '#CE1175',
    '#B64B01',
]
