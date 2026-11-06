import { getEmailQueuePriorityClass } from './email-priority'

describe('getEmailQueuePriorityClass', () => {
    it.each([
        ['transactional', 'fast'],
        ['marketing', 'bulk'],
        [undefined, 'bulk'],
    ] as const)('category %s classifies as %s', (categoryType, expected) => {
        expect(getEmailQueuePriorityClass({ message_category_type: categoryType })).toBe(expected)
    })

    it('classifies missing metadata as bulk', () => {
        expect(getEmailQueuePriorityClass(undefined)).toBe('bulk')
    })
})
