import { register } from 'prom-client'

import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'

import { EmailStatusOutput } from '../../outputs/outputs'
import { CyclotronJobInvocation, CyclotronJobInvocationResult } from '../../types'
import { TRANSACTIONAL_EMAIL_EVENT } from '../hogflows/hogflow-sensitivity'
import { EmailStatus, EmailStatusService, EmailStatusUpdate, buildEmailStatusRow } from './email-status.service'

const failedWrites = async (status: EmailStatus): Promise<number> =>
    (await register.getSingleMetric('cdp_email_status_write_failed')!.get()).values.find(
        (v) => v.labels.status === status
    )?.value ?? 0

describe('EmailStatusService', () => {
    const createdAt = Date.UTC(2026, 0, 2, 3, 4, 5, 678)
    const messageId = new UUIDT(createdAt).toString()

    it('builds a row whose created_at comes from the message id and whose version leads with the status rank', () => {
        const statusAt = new Date(Date.UTC(2026, 0, 3, 10, 0, 0, 123))

        expect(buildEmailStatusRow({ teamId: 2, messageId, status: 'bounced', reason: 'hard', statusAt })).toEqual({
            team_id: 2,
            message_id: messageId,
            status: 'bounced',
            // 6 * 2^48 + status_at in ms, as a decimal string for ClickHouse's UInt64.
            version: (6n * 2n ** 48n + BigInt(statusAt.getTime())).toString(),
            created_at: '2026-01-02 03:04:05.678000',
            status_at: '2026-01-03 10:00:00.123000',
            reason: 'hard',
        })
    })

    it('ranks every status above the previous one even when it is timestamped earlier', () => {
        const updates: Pick<EmailStatusUpdate, 'status' | 'reason' | 'runOutcome'>[] = [
            { status: 'queued' },
            { status: 'failed', reason: 'hog_error', runOutcome: true },
            { status: 'failed', reason: 'provider_error' },
            { status: 'sent' },
            { status: 'failed', reason: 'provider_rejected' },
            { status: 'delivered' },
            { status: 'bounced', reason: 'hard' },
            { status: 'complained' },
        ]
        const versions = updates.map((update, index) =>
            BigInt(
                buildEmailStatusRow({
                    teamId: 2,
                    messageId,
                    ...update,
                    // Each later status carries an earlier time, as a late webhook or a clock skew would.
                    statusAt: new Date(createdAt + (updates.length - index) * 60_000),
                }).version
            )
        )

        expect(versions).toEqual([...versions].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0)))
        expect(new Set(versions).size).toEqual(updates.length)
    })

    describe('run outcomes', () => {
        const runResult = (
            triggerEvent: string,
            outcome: Partial<Pick<CyclotronJobInvocationResult, 'error' | 'canceled' | 'finished'>>
        ): CyclotronJobInvocationResult =>
            ({
                invocation: {
                    id: messageId,
                    teamId: 2,
                    functionId: 'flow-id',
                    hogFlow: { id: 'flow-id' },
                    state: { event: { event: triggerEvent } },
                },
                finished: true,
                ...outcome,
            }) as unknown as CyclotronJobInvocationResult

        const producedRows = async (results: CyclotronJobInvocationResult[]): Promise<Record<string, any>[]> => {
            const produce = jest.fn().mockResolvedValue(undefined)
            const service = new EmailStatusService({ produce } as unknown as IngestionOutputs<EmailStatusOutput>, {
                EMAIL_STATUS_ENABLED: true,
            })
            service.queueInvocationResults(results)
            await service.flush()
            return produce.mock.calls.map(([, message]) => parseJSON(message.value.toString()))
        }

        it.each([
            [
                'records an errored transactional run as failed',
                TRANSACTIONAL_EMAIL_EVENT,
                { error: 'Template not found' },
                'hog_error',
            ],
            [
                'records a transactional run that timed out as failed',
                TRANSACTIONAL_EMAIL_EVENT,
                { error: new Error('Execution timed out') },
                'timeout',
            ],
            [
                'records a canceled transactional run as failed',
                TRANSACTIONAL_EMAIL_EVENT,
                { canceled: true },
                'canceled',
            ],
            ['records nothing for a transactional run that finished', TRANSACTIONAL_EMAIL_EVENT, {}, null],
            [
                'records nothing for a transactional run that is still in flight',
                TRANSACTIONAL_EMAIL_EVENT,
                { finished: false },
                null,
            ],
            ['records nothing for an errored workflow run', '$pageview', { error: 'Template not found' }, null],
            ['records nothing for a canceled workflow run', '$pageview', { canceled: true }, null],
        ])('%s', async (_desc, triggerEvent, outcome, reason) => {
            const rows = await producedRows([runResult(triggerEvent, outcome)])

            expect(rows).toEqual(
                reason ? [expect.objectContaining({ team_id: 2, message_id: messageId, status: 'failed', reason })] : []
            )
        })

        it.each([
            ['a sent email as sent', 'sent', undefined],
            // The transactional workflow aborts on a failed step, so a rejected send also fails its run.
            ['the reason of a send the provider rejected', 'failed', 'provider_error'],
        ] as const)('keeps %s when its run fails afterwards', async (_desc, status, reason) => {
            const step = buildEmailStatusRow({
                teamId: 2,
                messageId,
                status,
                reason,
                statusAt: new Date(createdAt + 1_000),
            })
            // The run fails after the step, so its row carries a later time.
            const [failed] = await producedRows([runResult(TRANSACTIONAL_EMAIL_EVENT, { error: 'Template not found' })])

            const latest = [step, failed].reduce((a, b) => (BigInt(b.version) > BigInt(a.version) ? b : a))
            expect(failed.status_at > step.status_at).toBe(true)
            expect(latest).toEqual(step)
        })
    })

    it.each([
        ['a transactional email', TRANSACTIONAL_EMAIL_EVENT, 1],
        ['a workflow run', '$pageview', 0],
    ])('records %s whose workflow is gone at dequeue as failed', async (_desc, triggerEvent, rows) => {
        const produce = jest.fn().mockResolvedValue(undefined)
        const service = new EmailStatusService({ produce } as unknown as IngestionOutputs<EmailStatusOutput>, {
            EMAIL_STATUS_ENABLED: true,
        })

        service.queueUnavailableRun({
            id: messageId,
            teamId: 2,
            state: { event: { event: triggerEvent } },
        } as unknown as CyclotronJobInvocation)
        await service.flush()

        expect(produce.mock.calls.map(([, message]) => parseJSON(message.value.toString()))).toEqual(
            rows ? [expect.objectContaining({ status: 'failed', reason: 'workflow_unavailable' })] : []
        )
    })

    it('returns from a flush whose produce stalls once the wait runs out', async () => {
        const produce = jest.fn(() => new Promise<void>(() => {}))
        const service = new EmailStatusService(
            { produce } as unknown as IngestionOutputs<EmailStatusOutput>,
            { EMAIL_STATUS_ENABLED: true },
            10
        )

        service.queue({ teamId: 2, messageId, status: 'sent' })

        await expect(service.flush()).resolves.toBeUndefined()
        expect(produce).toHaveBeenCalledTimes(1)
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
