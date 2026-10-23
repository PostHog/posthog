import { EMAIL_STATUS_OUTPUT, EmailStatusOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'

import { EmailStatusService } from './email-status.service'

describe('EmailStatusService', () => {
    const messageId = new UUIDT(Date.parse('2026-10-22T07:00:00.123Z')).toString()
    let outputs: jest.Mocked<IngestionOutputs<EmailStatusOutput>>
    let service: EmailStatusService

    const producedRows = (): Record<string, unknown>[] =>
        outputs.produce.mock.calls.map(([, message]) => parseJSON(message.value!.toString('utf8')))

    beforeEach(() => {
        outputs = { produce: jest.fn().mockResolvedValue(undefined) } as unknown as jest.Mocked<
            IngestionOutputs<EmailStatusOutput>
        >
        service = new EmailStatusService(outputs)
    })

    it('produces one row per status change, keyed by the message id', async () => {
        await service.record({
            teamId: 2,
            messageId,
            status: 'bounced',
            at: new Date('2026-10-22T07:05:00.456Z'),
            recipientHash: 'a1b2',
            reason: 'hard',
        })

        expect(outputs.produce).toHaveBeenCalledTimes(1)
        expect(outputs.produce.mock.calls[0][0]).toBe(EMAIL_STATUS_OUTPUT)
        expect(outputs.produce.mock.calls[0][1].key).toEqual(Buffer.from(messageId))
        expect(producedRows()).toEqual([
            {
                team_id: 2,
                message_id: messageId,
                status: 'bounced',
                // bounced ranks 6: 6 * 2^48 + the status time in ms
                version: 1690642512964392,
                created_at: '2026-10-22 07:00:00.123000',
                status_at: '2026-10-22 07:05:00.456000',
                reason: 'hard',
                recipient_hash: 'a1b2',
            },
        ])
    })

    it.each([['delivered' as const], ['failed' as const]])(
        'ranks %s above a sent that arrives after it',
        async (later) => {
            const change = { teamId: 2, messageId, recipientHash: 'a1b2' }
            await service.record({ ...change, status: later, at: new Date('2026-10-22T07:01:00Z') })
            await service.record({ ...change, status: 'sent', at: new Date('2026-10-22T07:02:00Z') })

            const [laterRow, sent] = producedRows()
            expect(laterRow.version as number).toBeGreaterThan(sent.version as number)
        }
    )

    it.each([
        ['provider_error', 'sent' as const],
        ['provider_error', 'skipped' as const],
        ['gave_up', 'sent' as const],
        ['gave_up', 'skipped' as const],
    ])('lets a rerun replace an attempt that failed with %s by its %s', async (reason, rerun) => {
        const change = { teamId: 2, messageId, recipientHash: 'a1b2' }
        await service.record({ ...change, status: 'failed', reason, at: new Date('2026-10-22T07:01:00Z') })
        await service.record({ ...change, status: rerun, at: new Date('2026-10-22T07:02:00Z') })

        const [failed, rerunRow] = producedRows()
        expect(rerunRow.version as number).toBeGreaterThan(failed.version as number)
    })
})
