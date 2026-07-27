import { FunnelsAlertConfig } from '~/queries/schema/schema-general'

import { funnelConfigForOptionKey, funnelConfigToOptionKey, funnelConversionOptions } from './funnelAlertOptions'

describe('funnelAlertOptions', () => {
    const flatValues = (labels: string[]): string[] =>
        funnelConversionOptions(labels).flatMap((section) => section.options.map((o) => ('value' in o ? o.value : '')))

    it('returns no options for a degenerate (<2 step) funnel', () => {
        expect(funnelConversionOptions([])).toEqual([])
        expect(funnelConversionOptions(['only'])).toEqual([])
    })

    it('collapses a 2-step funnel to a single overall option', () => {
        const sections = funnelConversionOptions(['Visited', 'Signed up'])
        expect(sections).toHaveLength(1)
        expect(sections[0].options).toEqual([{ label: 'Visited → Signed up', value: 'overall' }])
    })

    it('groups a 3-step funnel into step-over-step + a From-entry group holding just the overall', () => {
        const sections = funnelConversionOptions(['A', 'B', 'C'])
        expect(sections.map((s) => s.title)).toEqual(['Step-over-step', 'From entry'])
        // No intermediate cumulative step (start:2..N-2 is empty), so From entry holds only the overall.
        expect(flatValues(['A', 'B', 'C'])).toEqual(['prev:1', 'prev:2', 'overall'])
    })

    it('puts cumulative intermediates and the overall together in From entry (5-step funnel)', () => {
        const labels = ['Home', 'Product', 'Cart', 'Checkout', 'Order']
        const sections = funnelConversionOptions(labels)
        expect(sections.map((s) => s.title)).toEqual(['Step-over-step', 'From entry'])
        // start:1 (== prev:1) stays in step-over-step; the overall is the final From-entry member.
        expect(flatValues(labels)).toEqual(['prev:1', 'prev:2', 'prev:3', 'prev:4', 'start:2', 'start:3', 'overall'])
        // The overall row is labeled by its span (first → last), with no "overall" prefix.
        const fromEntry = sections.find((s) => s.title === 'From entry')!
        expect(fromEntry.options.map((o) => ('label' in o ? o.label : ''))).toEqual([
            'Home → Cart',
            'Home → Checkout',
            'Home → Order',
        ])
    })

    it('uses the real step labels in the option text', () => {
        const sections = funnelConversionOptions(['Home', 'Product', 'Cart'])
        const stepOverStep = sections.find((s) => s.title === 'Step-over-step')!
        expect(stepOverStep.options.map((o) => ('label' in o ? o.label : ''))).toEqual([
            'Home → Product',
            'Product → Cart',
        ])
    })

    const cfg = (metric: FunnelsAlertConfig['metric'], funnel_step: number | null): FunnelsAlertConfig => ({
        type: 'FunnelsAlertConfig',
        metric,
        funnel_step,
    })

    it.each([
        // [description, config, stepCount, expectedKey]
        ['null step → overall', cfg('conversion_from_start', null), 5, 'overall'],
        ['from_start at last step → overall', cfg('conversion_from_start', 4), 5, 'overall'],
        ['from_start at step 1 → prev:1 (coincident rate)', cfg('conversion_from_start', 1), 5, 'prev:1'],
        ['from_start at step 0 → prev:1', cfg('conversion_from_start', 0), 5, 'prev:1'],
        ['from_start intermediate → start:i', cfg('conversion_from_start', 2), 5, 'start:2'],
        ['from_previous → prev:i', cfg('conversion_from_previous', 3), 5, 'prev:3'],
        ['from_previous null → last step-over-step', cfg('conversion_from_previous', null), 5, 'prev:4'],
        ['from_previous at step 0 (invalid) → overall fallback', cfg('conversion_from_previous', 0), 5, 'overall'],
        ['2-step from_previous → overall', cfg('conversion_from_previous', 1), 2, 'overall'],
        ['2-step from_start → overall', cfg('conversion_from_start', null), 2, 'overall'],
    ])('funnelConfigToOptionKey: %s', (_desc, config, stepCount, expected) => {
        expect(funnelConfigToOptionKey(config, stepCount)).toBe(expected)
    })

    it.each([
        ['overall', { metric: 'conversion_from_start', funnel_step: null }],
        ['prev:2', { metric: 'conversion_from_previous', funnel_step: 2 }],
        ['start:3', { metric: 'conversion_from_start', funnel_step: 3 }],
    ])('funnelConfigForOptionKey: %s', (key, expected) => {
        expect(funnelConfigForOptionKey(key)).toEqual(expected)
    })

    it('round-trips every emitted option key back to a key that maps to the same rate', () => {
        const labels = ['Home', 'Product', 'Cart', 'Checkout', 'Order']
        const keys = flatValues(labels)
        const roundTripped = keys.map((key) =>
            funnelConfigToOptionKey({ type: 'FunnelsAlertConfig', ...funnelConfigForOptionKey(key) }, labels.length)
        )
        expect(roundTripped).toEqual(keys)
    })
})
