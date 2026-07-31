import { BREAKDOWN_BASELINE_STRING_LABEL } from 'scenes/insights/utils'

import { BreakdownItem, FunnelsActorsQuery } from '~/queries/schema/schema-general'

import { funnelBreakdownSelectValue, funnelStepBreakdownFromSelectValue } from './persons-modal-utils'

describe('persons modal funnel breakdown helpers', () => {
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
})
