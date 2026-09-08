import { HogFunctionType } from '../../types'

/**
 * Priority classes for the email cyclotron queue.
 *
 * Transactional email (receipts, password resets) is low-volume and
 * latency-sensitive; marketing email arrives in broadcast-sized bursts that
 * can queue millions of sends. Without classes, a team's own broadcast delays
 * that same team's transactional email behind the entire backlog, because the
 * per-team fair-dequeue counter is shared across all of a team's sends.
 *
 * 'fast' dequeues before 'bulk' (lower value wins, matching the hog/hogflow
 * queues' priority semantics). The SES rate-limit token bucket is claimed in
 * dequeue order, so dequeue priority is also send priority. Only the relative
 * order of the values matters: email rows are only ever compared against
 * other email rows, and routeToQueue restores the origin priority before a
 * job leaves the email queue.
 */
export type EmailQueuePriorityClass = 'fast' | 'bulk'

export const EMAIL_QUEUE_PRIORITY: Record<EmailQueuePriorityClass, number> = {
    fast: 0,
    bulk: 1,
}

/**
 * Classifies an email send from the ephemeral hog function's metadata, which
 * carries the flow action's config.
 *
 * The fast lane is opt-in: only sends explicitly categorized as transactional
 * get it, everything else (including uncategorized sends) is bulk. That keeps
 * the fast lane low-volume, which is what makes strict priority safe, and it
 * matches the category's other privileges (opt-out bypass, no unsubscribe
 * headers), which also apply only when transactional is declared.
 */
export function getEmailQueuePriorityClass(metadata: HogFunctionType['metadata']): EmailQueuePriorityClass {
    return metadata?.message_category_type === 'transactional' ? 'fast' : 'bulk'
}
