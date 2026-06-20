import type { YAxis } from './types'
import { resolveYAxisTitles, type YAxisTitles } from './y-axis-titles'

describe('resolveYAxisTitles', () => {
    it.each<[string, YAxis[] | undefined, string | undefined, YAxisTitles]>([
        ['the scalar label as the single left axis', undefined, 'Users', { left: 'Users' }],
        ['no titles when nothing is set', undefined, undefined, {}],
        [
            'a title per axis keyed by id',
            [
                { id: 'left', position: 'left', label: 'Revenue' },
                { id: 'right', position: 'right', label: 'Conversion' },
            ],
            'ignored',
            { left: 'Revenue', right: 'Conversion' },
        ],
        [
            'only the labeled axes',
            [
                { id: 'left', position: 'left' },
                { id: 'right', position: 'right', label: 'Conversion' },
            ],
            undefined,
            { right: 'Conversion' },
        ],
        ['the list over the scalar fallback', [{ id: 'left', position: 'left' }], 'Scalar', {}],
        [
            'three labeled axes',
            [
                { id: 'left', position: 'left', label: 'Revenue' },
                { id: 'axis-1', position: 'right', label: 'Signups' },
                { id: 'axis-2', position: 'right', label: 'Conversion' },
            ],
            undefined,
            { left: 'Revenue', 'axis-1': 'Signups', 'axis-2': 'Conversion' },
        ],
    ])('resolves %s', (_name, yAxes, yAxisLabel, expected) => {
        expect(resolveYAxisTitles(yAxes, yAxisLabel)).toEqual(expected)
    })
})
