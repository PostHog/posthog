import { FREE_LIMIT, isFreeTierCreateAtLimit } from './EditSubscription'

describe('EditSubscription free-tier gate', () => {
    it('FREE_LIMIT matches the backend free-tier value (5)', () => {
        expect(FREE_LIMIT).toBe(5)
    })

    it.each([
        ['empty (first use)', 0, false],
        ['one below the limit boundary', FREE_LIMIT - 1, false],
        ['at the limit', FREE_LIMIT, true],
        ['over the limit', FREE_LIMIT + 1, true],
    ])('blocks the next create when %s (count=%i) -> %s', (_desc, count, expected) => {
        expect(isFreeTierCreateAtLimit(count)).toBe(expected)
    })

    it('fails open while the count is unknown (null) so the form shows; backend enforces the hard limit', () => {
        expect(isFreeTierCreateAtLimit(null)).toBe(false)
    })
})
