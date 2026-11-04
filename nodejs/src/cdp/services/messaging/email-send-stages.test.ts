import { DateTime } from 'luxon'
import { register } from 'prom-client'

import { createExampleInvocation } from '../../_tests/fixtures'
import { EmailSendStageTimer } from './email-send-stages'
import { queueMetadataWithEmailWait } from './email-wait'

async function queueStageSum(): Promise<number> {
    const metric = await register.getSingleMetric('cdp_email_send_stage_ms')!.get()
    const values = metric.values as { labels: Record<string, string>; value: number; metricName?: string }[]
    const sample = values.find(
        (value) =>
            value.metricName === 'cdp_email_send_stage_ms_sum' &&
            value.labels.source === 'workflow' &&
            value.labels.stage === 'queue'
    )
    return sample?.value ?? 0
}

describe('EmailSendStageTimer', () => {
    it('starts the queue stage of a rescheduled send at its first due time', async () => {
        const invocation = createExampleInvocation()
        const firstDueAt = DateTime.utc().minus({ minutes: 10 })
        invocation.queueMetadata = queueMetadataWithEmailWait(
            { ...invocation, queueDueAt: firstDueAt },
            { teamCapped: false }
        )
        // The retry deadline the last reschedule set.
        invocation.queueDueAt = DateTime.utc().minus({ seconds: 1 })
        invocation.queueDequeuedAt = DateTime.utc()
        const before = await queueStageSum()

        new EmailSendStageTimer(invocation).record('workflow')

        expect((await queueStageSum()) - before).toBeGreaterThanOrEqual(10 * 60 * 1000)
    })
})
