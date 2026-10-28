import { register } from 'prom-client'

import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { UUIDT } from '~/common/utils/utils'

import { EmailStatusOutput } from '../../outputs/outputs'
import { EmailStatus, EmailStatusService, buildEmailStatusRow } from './email-status.service'

const failedWrites = async (status: EmailStatus): Promise<number> =>
    (await register.getSingleMetric('cdp_email_status_write_failed')!.get()).values.find(
        (v) => v.labels.status === status
    )?.value ?? 0

describe('EmailStatusService', () => {
    const createdAt = Date.UTC(2026, 0, 2, 3, 4, 5, 678)
    const messageId = new UUIDT(createdAt).toString()

    it('builds a row whose created_at comes from the message id and whose version leads with the status rank', () => {
        const statusAt = new Date(Date.UTC(2026, 0, 3, 10, 0, 0, 123))

        expect(
            buildEmailStatusRow({ teamId: 2, messageId, status: 'failed', reason: 'provider_error', statusAt })
        ).toEqual({
            team_id: 2,
            message_id: messageId,
            status: 'failed',
            // 1 * 2^48 + status_at in ms, as a decimal string for ClickHouse's UInt64.
            version: (1n * 2n ** 48n + BigInt(statusAt.getTime())).toString(),
            created_at: '2026-01-02 03:04:05.678000',
            status_at: '2026-01-03 10:00:00.123000',
            reason: 'provider_error',
        })
    })

    it('ranks every status above the previous one even when it is timestamped earlier', () => {
        const statuses: EmailStatus[] = ['queued', 'failed', 'sent', 'delivered', 'bounced', 'complained']
        const versions = statuses.map((status, index) =>
            BigInt(
                buildEmailStatusRow({
                    teamId: 2,
                    messageId,
                    status,
                    // Each later status carries an earlier time, as a late webhook or a clock skew would.
                    statusAt: new Date(createdAt + (statuses.length - index) * 60_000),
                }).version
            )
        )

        expect(versions).toEqual([...versions].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0)))
        expect(new Set(versions).size).toEqual(statuses.length)
    })

    it.each([
        ['the produce fails', messageId, () => Promise.reject(new Error('broker down'))],
        ['the message id is not a UUID', 'not-a-uuid', () => Promise.resolve()],
    ])('drops and counts a row when %s, and still writes the others', async (_desc, badMessageId, produceBad) => {
        const otherMessageId = new UUIDT().toString()
        const produce = jest.fn((_output, message: { key: Buffer }) =>
            message.key.toString() === badMessageId ? produceBad() : Promise.resolve()
        )
        const service = new EmailStatusService({ produce } as unknown as IngestionOutputs<EmailStatusOutput>, {
            EMAIL_STATUS_ENABLED: true,
        })
        const failedBefore = await failedWrites('delivered')

        service.queue({ teamId: 2, messageId: badMessageId, status: 'delivered' })
        service.queue({ teamId: 2, messageId: otherMessageId, status: 'delivered' })
        await expect(service.flush()).resolves.toBeUndefined()

        expect(await failedWrites('delivered')).toEqual(failedBefore + 1)
        expect(produce.mock.calls.map(([, message]) => message.key.toString())).toContain(otherMessageId)
    })
})
