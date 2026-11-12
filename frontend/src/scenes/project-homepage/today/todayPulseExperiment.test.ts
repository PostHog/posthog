import type { HighlightExperimentResultApi } from 'products/today/frontend/generated/api.schemas'

import {
    experimentComparison,
    experimentLiftDecimals,
    experimentExposures,
    experimentTone,
    experimentVerdict,
} from './todayPulseExperiment'

const RESULT: HighlightExperimentResultApi = {
    metric_name: 'Conversion rate',
    variant: 'test',
    control: 'control',
    variants: 1,
    significant: true,
    favorable: true,
    exposures: 4100,
}

describe('todayPulseExperiment', () => {
    test.each([
        ['a significant win', {}, 'good', 'vs control', 'Significant', '4,100 exposed'],
        ['a significant loss', { favorable: false }, 'risk', 'vs control', 'Significant', '4,100 exposed'],
        ['an unclear lead', { significant: false }, 'neutral', 'vs control', 'Not significant', '4,100 exposed'],
        [
            'one of several variants',
            { variants: 2, variant: 'calm' },
            'good',
            'calm vs control',
            'Significant',
            '4,100 exposed',
        ],
    ])('%s', (_name, overrides, tone, comparison, verdict, exposed) => {
        const experiment = { ...RESULT, ...overrides }

        expect([
            experimentTone(experiment),
            experimentComparison(experiment),
            experimentVerdict(experiment),
            experimentExposures(experiment),
        ]).toEqual([tone, comparison, verdict, exposed])
    })

    test.each([
        [0.4, 2],
        [-0.06, 2],
        [8.2, 1],
        [-12.5, 0],
    ])('shows a lift of %s with %s decimals', (lift, decimals) => {
        expect(experimentLiftDecimals(lift)).toBe(decimals)
    })
})
