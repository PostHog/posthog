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
 * carries the flow action's config plus the flow's trigger type.
 *
 * An explicit message_category_type wins. Uncategorized sends default to
 * 'fast' because many existing event-triggered transactional flows never set
 * a category, and silently demoting them would regress their latency; the
 * batch-trigger check still catches unlabeled broadcasts, which are where the
 * volume actually comes from.
 */
export function getEmailQueuePriorityClass(metadata: HogFunctionType['metadata']): EmailQueuePriorityClass {
    const categoryType = metadata?.message_category_type
    if (categoryType === 'transactional') {
        return 'fast'
    }
    if (categoryType === 'marketing') {
        return 'bulk'
    }
    return metadata?.trigger_type === 'batch' ? 'bulk' : 'fast'
}
