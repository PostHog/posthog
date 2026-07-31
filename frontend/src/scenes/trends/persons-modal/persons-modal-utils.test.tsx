import { render, screen } from '@testing-library/react'

import { BREAKDOWN_BASELINE_STRING_LABEL } from 'scenes/insights/utils'

import { BreakdownItem, FunnelsActorsQuery } from '~/queries/schema/schema-general'
import { EntityTypes } from '~/types'

import {
    funnelBreakdownSelectValue,
    funnelStepBreakdownFromSelectValue,
    funnelStepLabel,
    funnelTitle,
    trendSeriesTitle,
} from './persons-modal-utils'

describe('persons modal title helpers', () => {
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

    describe('funnelStepLabel', () => {
        it.each<[string, Parameters<typeof funnelStepLabel>[0], string]>([
            ['all-events step', { action_id: null, name: null, type: EntityTypes.EVENTS }, 'All events'],
            ['event step', { action_id: '$pageview', name: '$pageview', type: EntityTypes.EVENTS }, '$pageview'],
            [
                'custom name wins',
                { action_id: '$pageview', name: '$pageview', custom_name: 'Landed', type: EntityTypes.EVENTS },
                'Landed',
            ],
        ])('labels a %s', (_name, step, expected) => {
            expect(funnelStepLabel(step)).toEqual(expected)
        })
    })

    describe('rendered titles', () => {
        it('renders a trend series title through the event taxonomy', () => {
            render(<>{trendSeriesTitle('$pageview')}</>)
            expect(screen.getByText('Pageview')).toBeTruthy()
        })

        it('renders an all-events funnel step as "All events"', () => {
            render(
                funnelTitle({
                    converted: true,
                    step: 8,
                    label: funnelStepLabel({
                        action_id: null,
                        name: null,
                        type: EntityTypes.EVENTS,
                    }),
                })
            )
            expect(screen.getByText('All events')).toBeTruthy()
        })
    })
})
