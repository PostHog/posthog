import { getEmailQueuePriorityClass } from './email-priority'

describe('getEmailQueuePriorityClass', () => {
    it.each([
        ['transactional', 'event', 'fast'],
        ['transactional', 'batch', 'fast'],
        ['marketing', 'event', 'bulk'],
        ['marketing', 'batch', 'bulk'],
        [undefined, 'event', 'fast'],
        [undefined, 'batch', 'bulk'],
        [undefined, undefined, 'fast'],
    ] as const)('category %s with trigger %s classifies as %s', (categoryType, triggerType, expected) => {
        expect(getEmailQueuePriorityClass({ message_category_type: categoryType, trigger_type: triggerType })).toBe(
            expected
        )
    })

    it('classifies missing metadata as fast', () => {
        expect(getEmailQueuePriorityClass(undefined)).toBe('fast')
    })
})
