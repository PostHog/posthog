import { PREDICTION_SEGMENTS, predictionSegmentCohortFilters, predictionSegmentFor } from './predictionSegments'

function cohortMatches(filters: ReturnType<typeof predictionSegmentCohortFilters>, probability: number): boolean {
    return filters.properties.values.every((group) =>
        'values' in group
            ? group.values.every((condition) => {
                  const { operator, value } = condition as { operator: string; value: number }
                  return operator === 'gte' ? probability >= value : probability < value
              })
            : false
    )
}

describe('predictionSegments', () => {
    test.each(Array.from({ length: 21 }, (_, step) => step / 20))(
        'a %s score lands in exactly one segment cohort, the one its histogram bar is colored as',
        (probability) => {
            const matching = PREDICTION_SEGMENTS.filter(({ key }) =>
                cohortMatches(predictionSegmentCohortFilters(key, 'p_signed_up'), probability)
            )

            expect(matching.map(({ key }) => key)).toEqual([predictionSegmentFor(probability).key])
        }
    )
})
