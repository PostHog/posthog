import type { HighlightExperimentResultApi } from 'products/today/frontend/generated/api.schemas'

import { experimentComparison, experimentPeople, experimentTone, experimentVerdict } from './todayPulseExperiment'

const RESULT: HighlightExperimentResultApi = {
    metric_name: 'Conversion rate',
    variant: 'test',
    control: 'control',
    variants: 1,
    significant: true,
    favorable: true,
    people: 4100,
}

describe('todayPulseExperiment', () => {
    test.each([
        ['a significant win', {}, 'good', 'vs control', 'Significant', '4,100 people'],
        ['a significant loss', { favorable: false }, 'risk', 'vs control', 'Significant', '4,100 people'],
        ['an unclear lead', { significant: false }, 'neutral', 'vs control', 'Not significant', '4,100 people'],
        [
            'one of several variants',
            { variants: 2, variant: 'calm' },
            'good',
            'calm vs control',
            'Significant',
            '4,100 people',
        ],
        ['one person', { people: 1 }, 'good', 'vs control', 'Significant', '1 person'],
    ])('%s', (_name, overrides, tone, comparison, verdict, people) => {
        const experiment = { ...RESULT, ...overrides }

        expect([
            experimentTone(experiment),
            experimentComparison(experiment),
            experimentVerdict(experiment),
            experimentPeople(experiment),
        ]).toEqual([tone, comparison, verdict, people])
    })
})
