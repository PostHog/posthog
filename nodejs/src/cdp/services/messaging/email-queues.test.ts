import { buildIntegerMatcher } from '~/common/config/matchers'

import { EMAIL_QUEUE, EMAIL_TRANSACTIONAL_QUEUE, getEmailQueue, isEmailQueue } from './email-queues'

describe('email queues', () => {
    const allTeams = buildIntegerMatcher('*', true)

    it.each([
        ['transactional', EMAIL_TRANSACTIONAL_QUEUE],
        ['marketing', EMAIL_QUEUE],
        [undefined, EMAIL_QUEUE],
    ] as const)('category %s routes to %s', (categoryType, expected) => {
        expect(getEmailQueue({ message_category_type: categoryType }, 2, allTeams)).toBe(expected)
    })

    it('routes missing metadata to the marketing lane', () => {
        expect(getEmailQueue(undefined, 2, allTeams)).toBe(EMAIL_QUEUE)
    })

    it('keeps a transactional send on the marketing lane for a team outside the rollout', () => {
        const onlyTeamTwo = buildIntegerMatcher('2', true)
        expect(getEmailQueue({ message_category_type: 'transactional' }, 2, onlyTeamTwo)).toBe(
            EMAIL_TRANSACTIONAL_QUEUE
        )
        expect(getEmailQueue({ message_category_type: 'transactional' }, 3, onlyTeamTwo)).toBe(EMAIL_QUEUE)
    })

    it('recognises both lanes and nothing else', () => {
        expect(isEmailQueue(EMAIL_QUEUE)).toBe(true)
        expect(isEmailQueue(EMAIL_TRANSACTIONAL_QUEUE)).toBe(true)
        expect(isEmailQueue('hogflow')).toBe(false)
        expect(isEmailQueue(undefined)).toBe(false)
    })
})
