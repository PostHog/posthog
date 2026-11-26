import { fitCount } from './fitCount'

describe('fitCount', () => {
    test.each([
        { name: 'every item when they all fit', widths: [100, 100], available: 208, expected: 2 },
        {
            name: 'one fewer when the last fits only without the more button',
            widths: [100, 100, 100],
            available: 250,
            expected: 1,
        },
        {
            name: 'none when even the first leaves no room for the more button',
            widths: [200, 100],
            available: 250,
            expected: 0,
        },
    ])('shows $name', ({ widths, available, expected }) => {
        expect(fitCount(widths, available, 80)).toBe(expected)
    })
})
