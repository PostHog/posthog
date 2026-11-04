import { DateTime } from 'luxon'
import { Histogram } from 'prom-client'

import { CyclotronJobInvocationHogFunction } from '../../types'
import { readEmailWait } from './email-wait'

const EMAIL_SEND_STAGES = [
    'queue',
    'pre_send',
    'integration',
    'suspension',
    'suppression',
    'tracking',
    'workflow_rate_limit',
    'team_cap',
    'render',
    'ses_call',
] as const
export type EmailSendStage = (typeof EMAIL_SEND_STAGES)[number]

const emailSendStageMs = new Histogram({
    name: 'cdp_email_send_stage_ms',
    help: 'Milliseconds an accepted fast-lane email send spent in each stage: queue (first due time to the last dequeue, retries included), pre_send (dequeue to the email service), each awaited step of the send, render (building the message), and ses_call (the SES request alone). Each stage observes once per accepted send; the steps after queue time only the accepted attempt. Bulk sends observe nothing.',
    labelNames: ['source', 'stage'],
    buckets: [25, 50, 100, 250, 500, 1_000, 2_500, 5_000, 10_000, 30_000, 60_000, 120_000, 300_000],
})

// increase() reads a series' first sample as its baseline, so a series created by the first send hides it.
for (const source of ['transactional_api', 'workflow']) {
    for (const stage of EMAIL_SEND_STAGES) {
        emailSendStageMs.zero({ source, stage })
    }
}

// Holds the timings of one send attempt, so that only the attempt SES accepts records them.
export class EmailSendStageTimer {
    private readonly durations: [EmailSendStage, number][] = []

    constructor(invocation: CyclotronJobInvocationHogFunction, enteredAt: number = Date.now()) {
        const { queueDueAt, queueDequeuedAt } = invocation
        if (queueDueAt && queueDequeuedAt) {
            // A reschedule moves queueDueAt to the retry deadline, so the queue stage starts at the send's first due time.
            const firstDueAt = readEmailWait(invocation)?.firstDueAt
            const dueAtMs = firstDueAt ? DateTime.fromISO(firstDueAt).toMillis() : queueDueAt.toMillis()
            this.durations.push(['queue', queueDequeuedAt.toMillis() - dueAtMs])
            this.durations.push(['pre_send', enteredAt - queueDequeuedAt.toMillis()])
        }
    }

    public async time<T>(stage: EmailSendStage, step: () => Promise<T>): Promise<T> {
        const startedAt = performance.now()
        try {
            return await step()
        } finally {
            this.durations.push([stage, performance.now() - startedAt])
        }
    }

    public add(stage: EmailSendStage, durationMs: number): void {
        this.durations.push([stage, durationMs])
    }

    public record(source: string): void {
        for (const [stage, durationMs] of this.durations) {
            emailSendStageMs.labels({ source, stage }).observe(Math.max(0, durationMs))
        }
    }
}
