import { ValueMatcher } from '~/types'

import { CyclotronJobQueueKind, HogFunctionType } from '../../types'

/**
 * A lane each, so a marketing backlog, a bad rollout or a stuck pod on one
 * cannot hold up the other. Run-together spelling because a queue name is
 * interpolated into Kafka topic and consumer group names, as `hogoverflow` is.
 */
export const EMAIL_QUEUE = 'email' satisfies CyclotronJobQueueKind
export const EMAIL_TRANSACTIONAL_QUEUE = 'emailtransactional' satisfies CyclotronJobQueueKind

export type EmailQueue = typeof EMAIL_QUEUE | typeof EMAIL_TRANSACTIONAL_QUEUE

export function isEmailQueue(queue: string | undefined | null): queue is EmailQueue {
    return queue === EMAIL_QUEUE || queue === EMAIL_TRANSACTIONAL_QUEUE
}

/**
 * The transactional lane is opt-in: an uncategorized send stays on the marketing
 * lane. That keeps the lane low-volume, which is what makes its claim on
 * reserved SES capacity affordable, and it matches the category's other
 * privileges (opt-out bypass, no unsubscribe headers).
 */
export function getEmailQueue(
    metadata: HogFunctionType['metadata'],
    teamId: number,
    transactionalTeams: ValueMatcher<number>
): EmailQueue {
    return metadata?.message_category_type === 'transactional' && transactionalTeams(teamId)
        ? EMAIL_TRANSACTIONAL_QUEUE
        : EMAIL_QUEUE
}
