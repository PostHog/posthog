import { NodeKind } from '~/queries/schema/schema-general'

import { isBoxPlotMissingProperty } from './isBoxPlotMissingProperty'

describe('isBoxPlotMissingProperty', () => {
    it('returns true when there are no series', () => {
        expect(isBoxPlotMissingProperty([])).toBe(true)
    })

    it('returns true when a series is missing math_property', () => {
        expect(
            isBoxPlotMissingProperty([
                { kind: NodeKind.EventsNode, event: '$pageview', math_property: 'duration' },
                { kind: NodeKind.EventsNode, event: '$signup' },
            ])
        ).toBe(true)
    })

    it('returns false when all series have math_property', () => {
        expect(
            isBoxPlotMissingProperty([
                { kind: NodeKind.EventsNode, event: '$pageview', math_property: 'duration' },
                { kind: NodeKind.EventsNode, event: '$signup', math_property: 'revenue' },
            ])
        ).toBe(false)
    })
})
