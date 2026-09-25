import { BREAKDOWN_BASELINE_STRING_LABEL, BREAKDOWN_NULL_STRING_LABEL } from 'scenes/insights/utils'

import { BreakdownItem, FunnelsActorsQuery, InsightActorsQuery, NodeKind } from '~/queries/schema/schema-general'

import {
    funnelBreakdownSelectValue,
    funnelStepBreakdownFromSelectValue,
    nullBreakdownNotesForQuery,
} from './persons-modal-utils'

describe('persons modal breakdown helpers', () => {
    const options: BreakdownItem[] = [
        { label: 'Baseline', value: BREAKDOWN_BASELINE_STRING_LABEL },
        { label: 'Chrome', value: 'Chrome' },
        { label: 'Chrome, Mac OS X', value: '["Chrome","Mac OS X"]' },
        { label: 'my cohort', value: 2 },
    ]

    describe('funnelStepBreakdownFromSelectValue', () => {
        it.each<[string | number | null, FunnelsActorsQuery['funnelStepBreakdown']]>([
            [BREAKDOWN_BASELINE_STRING_LABEL, null],
            [null, null],
            ['Chrome', 'Chrome'],
            [2, 2],
            ['["Chrome","Mac OS X"]', ['Chrome', 'Mac OS X']],
            ['[not json', '[not json'],
        ])('maps selection %p to funnelStepBreakdown %p', (selection, expected) => {
            expect(funnelStepBreakdownFromSelectValue(selection)).toEqual(expected)
        })
    })

    describe('funnelBreakdownSelectValue', () => {
        it.each<[FunnelsActorsQuery['funnelStepBreakdown'] | undefined, string | number | null]>([
            [null, BREAKDOWN_BASELINE_STRING_LABEL],
            [undefined, BREAKDOWN_BASELINE_STRING_LABEL],
            ['Chrome', 'Chrome'],
            [['Chrome'], 'Chrome'], // single-element arrays match their unwrapped option
            [['Chrome', 'Mac OS X'], '["Chrome","Mac OS X"]'],
            ['2', 2], // numeric/string drift between result values and option values
            ['Safari', null], // no matching option must not fall back to Baseline
        ])('maps funnelStepBreakdown %p to selection %p', (funnelStepBreakdown, expected) => {
            expect(funnelBreakdownSelectValue(funnelStepBreakdown, options)).toEqual(expected)
        })
    })

    describe('nullBreakdownNotesForQuery', () => {
        const trendsActorsQuery = (
            breakdown: InsightActorsQuery['breakdown'],
            breakdownFilter: Record<string, unknown>
        ): InsightActorsQuery =>
            ({
                kind: NodeKind.InsightActorsQuery,
                breakdown,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                    breakdownFilter,
                },
            }) as InsightActorsQuery

        it('explains the bucket the modal drills into', () => {
            expect(
                nullBreakdownNotesForQuery(
                    trendsActorsQuery(BREAKDOWN_NULL_STRING_LABEL, {
                        breakdown: '$pathname',
                        breakdown_type: 'event',
                    })
                )?.explanation
            ).toContain('Path name')
        })

        it('says nothing for a bucket that has a value', () => {
            expect(
                nullBreakdownNotesForQuery(
                    trendsActorsQuery('/pricing', { breakdown: '$pathname', breakdown_type: 'event' })
                )
            ).toBeNull()
        })

        // A funnel carries its breakdown in its own field, and encodes a missing property as an
        // empty string wrapped in an array, where the other queries send the null sentinel.
        it.each([
            ['the null sentinel', BREAKDOWN_NULL_STRING_LABEL],
            ['an empty string', ['']],
        ])('reads the breakdown of a funnel actors query, which uses its own field: %s', (_name, breakdown) => {
            expect(
                nullBreakdownNotesForQuery({
                    kind: NodeKind.FunnelsActorsQuery,
                    funnelStepBreakdown: breakdown,
                    source: {
                        kind: NodeKind.FunnelsQuery,
                        series: [],
                        breakdownFilter: { breakdown: '$pathname', breakdown_type: 'event' },
                    },
                } as unknown as FunnelsActorsQuery)?.explanation
            ).toContain('Path name')
        })
    })
})
