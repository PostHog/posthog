import { FEATURE_FLAGS } from 'lib/constants'

import { inCanvasExperiment } from './canvasExperiment'

describe('inCanvasExperiment', () => {
    test.each([
        { canvasExperiment: true, railNav: true, expected: true },
        { canvasExperiment: false, railNav: true, expected: false },
        { canvasExperiment: true, railNav: false, expected: false },
        { canvasExperiment: false, railNav: false, expected: false },
    ])(
        'canvas-experiment $canvasExperiment and today-rail-nav $railNav gives $expected',
        ({ canvasExperiment, railNav, expected }) => {
            expect(
                inCanvasExperiment({
                    [FEATURE_FLAGS.CANVAS_EXPERIMENT]: canvasExperiment,
                    [FEATURE_FLAGS.TODAY_RAIL_NAV]: railNav,
                })
            ).toBe(expected)
        }
    )
})
