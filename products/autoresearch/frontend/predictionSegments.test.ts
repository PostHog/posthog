import { parseWorkflowTriggerPrefill } from 'products/workflows/frontend/Workflows/workflowTriggerPrefill'

import {
    PredictionSegmentThresholds,
    likelySegmentWorkflowUrl,
    predictionSegmentCohortFilters,
    predictionSegmentDefinitions,
    predictionSegmentFor,
    predictionSegmentForRange,
} from './predictionSegments'

const FIXED: PredictionSegmentThresholds = { likely_threshold: 0.6, possible_threshold: 0.2, base_rate: null }
const RARE: PredictionSegmentThresholds = { likely_threshold: 0.045, possible_threshold: 0.015, base_rate: 0.015 }
const CAPPED: PredictionSegmentThresholds = { likely_threshold: 0.75, possible_threshold: 0.5, base_rate: 0.5 }

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
    test.each([
        ['fixed', FIXED],
        ['rare target', RARE],
        ['capped', CAPPED],
    ])(
        'with %s cut points, every score lands in exactly one segment cohort, the one its card counts',
        (_, thresholds) => {
            const { likely_threshold: high, possible_threshold: low } = thresholds
            const scores = [...Array.from({ length: 21 }, (_, step) => step / 20), high, low, high - 1e-9, low - 1e-9]
            for (const probability of scores) {
                const matching = predictionSegmentDefinitions(thresholds).filter(({ key }) =>
                    cohortMatches(predictionSegmentCohortFilters(key, 'p_signed_up', thresholds), probability)
                )

                expect(matching.map(({ key }) => key)).toEqual([predictionSegmentFor(probability, thresholds).key])
            }
        }
    )

    test.each([
        ['fixed', FIXED, ['60% and above', '20% to 60%', 'Below 20%'], ['60% and above', '20% to 60%', 'Below 20%']],
        [
            'rare target',
            RARE,
            ['3× average or higher (4.5%+)', 'Average to 3× (1.5% to 4.5%)', 'Below average (under 1.5%)'],
            ['4.5% and above', '1.5% to 4.5%', 'Below 1.5%'],
        ],
        [
            'capped',
            CAPPED,
            ['1.5× average or higher (75%+)', 'Average to 1.5× (50% to 75%)', 'Below average (under 50%)'],
            ['75% and above', '50% to 75%', 'Below 50%'],
        ],
    ])('%s cut points state the lift and the probabilities', (_, thresholds, ranges, probabilityRanges) => {
        const segments = predictionSegmentDefinitions(thresholds)

        expect(segments.map(({ range }) => range)).toEqual(ranges)
        expect(segments.map(({ probabilityRange }) => probabilityRange)).toEqual(probabilityRanges)
    })

    test.each([
        ['a bar inside one segment keeps its color', 0.6, 0.7, FIXED, 'likely'],
        ['a bar a cut point splits is neutral', 0.0, 0.1, RARE, null],
        ['a bar starting at a cut point is not split', 0.5, 0.6, CAPPED, 'possible'],
    ])('%s', (_, lower, upper, thresholds, expected) => {
        expect(predictionSegmentForRange(lower, upper, thresholds)?.key ?? null).toEqual(expected)
    })

    test('the workflow link opens a batch workflow whose audience is the likely segment', () => {
        const raw = new URLSearchParams(likelySegmentWorkflowUrl('p_signed_up', RARE).split('?')[1]).get('trigger')

        expect(parseWorkflowTriggerPrefill(raw ?? undefined)).toEqual({
            type: 'batch',
            filters: { properties: [{ type: 'person', key: 'p_signed_up', operator: 'gte', value: 0.045 }] },
        })
    })
})
