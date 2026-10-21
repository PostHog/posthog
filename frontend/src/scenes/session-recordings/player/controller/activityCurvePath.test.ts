import { activityAreaPath } from './activityCurvePath'

describe('activityAreaPath', () => {
    const points = [
        { x: 0, y: 10 },
        { x: 5, y: 2 },
        { x: 10, y: 8 },
    ]

    it.each([
        { name: 'no points', input: [], smooth: true, expected: /^$/ },
        { name: 'straight segments', input: points, smooth: false, expected: /^M 0,10 L 0,10 L 5,2 L 10,8 L 10,10 Z$/ },
        {
            name: 'a smooth curve through the same points',
            input: points,
            smooth: true,
            expected: /^M 0,10 L 0,10 C .* 5,2 C .* 10,8 L 10,10 Z$/,
        },
    ])('draws $name', ({ input, smooth, expected }) => {
        expect(activityAreaPath(input, 10, 10, smooth)).toMatch(expected)
    })
})
