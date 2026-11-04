import { Histogram } from 'prom-client'

import { CyclotronJobInvocationHogFunction } from '../../types'

export type EmailSendStage =
    | 'queue'
    | 'pre_send'
    | 'integration'
    | 'suspension'
    | 'suppression'
    | 'tracking'
    | 'workflow_rate_limit'
    | 'team_cap'
    | 'ses_call'

const emailSendStageMs = new Histogram({
    name: 'cdp_email_send_stage_ms',
    help: 'Milliseconds an accepted fast-lane email send spent in each stage: queue (due to dequeue), pre_send (dequeue to the email service), then each awaited step of the send up to and including the SES call. Each stage observes once per accepted send. Bulk sends observe nothing.',
    labelNames: ['source', 'stage'],
    buckets: [25, 50, 100, 250, 500, 1_000, 2_500, 5_000, 10_000, 30_000, 60_000, 120_000, 300_000],
})

// Holds the timings of one send attempt, so that only the attempt SES accepts records them.
export class EmailSendStageTimer {
    private readonly durations: [EmailSendStage, number][] = []

    constructor(invocation: CyclotronJobInvocationHogFunction, enteredAt: number = Date.now()) {
        const { queueDueAt, queueDequeuedAt } = invocation
        if (queueDueAt && queueDequeuedAt) {
            this.durations.push(['queue', queueDequeuedAt.toMillis() - queueDueAt.toMillis()])
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

    public record(source: string): void {
        for (const [stage, durationMs] of this.durations) {
            emailSendStageMs.labels({ source, stage }).observe(Math.max(0, durationMs))
        }
    }
}
