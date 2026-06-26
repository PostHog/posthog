import { CyclotronInvocationQueueParametersEmailType } from '~/cdp/schema/cyclotron'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { parseJSON } from '~/common/utils/json-parse'

import { createExampleInvocation } from '../../_tests/fixtures'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult, MessageAssetRow } from '../../types'
import { MessageAssetsService } from './message-assets.service'

const CONFIG = {
    MESSAGE_ASSETS_CAPTURE_ENABLED: true,
}

const buildOutputsMock = (): jest.Mocked<IngestionOutputs<'message_assets'>> =>
    ({ produce: jest.fn().mockResolvedValue(undefined) }) as unknown as jest.Mocked<IngestionOutputs<'message_assets'>>

const emailParams = (
    overrides: Partial<CyclotronInvocationQueueParametersEmailType> = {}
): CyclotronInvocationQueueParametersEmailType =>
    ({
        type: 'email',
        to: { email: 'recipient@example.com' },
        from: { integrationId: 1 },
        subject: 'Welcome aboard',
        text: 'plain text',
        html: '<p>Hello</p>',
        ...overrides,
    }) as CyclotronInvocationQueueParametersEmailType

const invocationWithAction = (id: string, teamId = 7): CyclotronJobInvocationHogFunction => {
    const invocation = createExampleInvocation({ id, team_id: teamId })
    invocation.state.actionId = 'email-step'
    return invocation
}

const resultWith = (assets: MessageAssetRow[]): CyclotronJobInvocationResult =>
    ({
        emailAssets: assets,
    }) as unknown as CyclotronJobInvocationResult

const producedRowAt = (outputs: jest.Mocked<IngestionOutputs<'message_assets'>>, index: number): MessageAssetRow => {
    const call = outputs.produce.mock.calls[index]
    const value = (call[1] as { value: Buffer }).value
    return parseJSON(value.toString('utf8')) as MessageAssetRow
}

describe('MessageAssetsService', () => {
    let outputs: jest.Mocked<IngestionOutputs<'message_assets'>>
    let service: MessageAssetsService

    beforeEach(() => {
        jest.clearAllMocks()
        outputs = buildOutputsMock()
        service = new MessageAssetsService(outputs, CONFIG)
    })

    describe('buildRowForEmail', () => {
        it('returns a populated row for an in-workflow email step', () => {
            const invocation = invocationWithAction('flow-1', 7)

            const row = service.buildRowForEmail(invocation, emailParams())

            expect(row).not.toBeNull()
            expect(row!.team_id).toBe(7)
            expect(row!.function_id).toBe('flow-1')
            expect(row!.invocation_id).toBe(invocation.id)
            expect(row!.action_id).toBe('email-step')
            expect(row!.function_kind).toBe('hog_flow')
            expect(row!.kind).toBe('email')
            expect(row!.status).toBe('sent')
            expect(row!.recipient).toBe('recipient@example.com')
            expect(row!.subject).toBe('Welcome aboard')
            expect(row!.html).toBe('<p>Hello</p>')
        })

        it('returns null for a standalone email send (no action id — unretrievable from the Assets API)', () => {
            const invocation = createExampleInvocation({ id: 'fn-1', team_id: 3 })

            const row = service.buildRowForEmail(invocation, emailParams())

            expect(row).toBeNull()
        })

        it('returns null when capture is globally disabled', () => {
            service = new MessageAssetsService(outputs, { MESSAGE_ASSETS_CAPTURE_ENABLED: false })

            const row = service.buildRowForEmail(invocationWithAction('flow-1'), emailParams())

            expect(row).toBeNull()
        })

        it('returns null for text-only emails (no HTML to snapshot)', () => {
            const row = service.buildRowForEmail(invocationWithAction('flow-1'), emailParams({ html: '' }))

            expect(row).toBeNull()
        })
    })

    describe('queueInvocationResults + flush', () => {
        it('does not produce anything until flush is called', () => {
            const row = service.buildRowForEmail(invocationWithAction('flow-1'), emailParams())!

            service.queueInvocationResults([resultWith([row])])

            expect(outputs.produce).not.toHaveBeenCalled()
        })

        it('bulk-produces every queued row on flush', async () => {
            const row1 = service.buildRowForEmail(invocationWithAction('flow-1'), emailParams())!
            const row2 = service.buildRowForEmail(invocationWithAction('flow-2'), emailParams({ subject: 'Second' }))!

            service.queueInvocationResults([resultWith([row1]), resultWith([row2])])
            await service.flush()

            expect(outputs.produce).toHaveBeenCalledTimes(2)
            const subjects = [producedRowAt(outputs, 0).subject, producedRowAt(outputs, 1).subject].sort()
            expect(subjects).toEqual(['Second', 'Welcome aboard'])
        })

        it('partitions each row by invocation_id so retries collapse via the ReplacingMergeTree', async () => {
            const row = service.buildRowForEmail(invocationWithAction('flow-1'), emailParams())!

            service.queueInvocationResults([resultWith([row])])
            await service.flush()

            const key = (outputs.produce.mock.calls[0][1] as { key: Buffer }).key
            expect(key.toString('utf8')).toBe(row.invocation_id)
        })

        it('clears the buffer after a successful flush so a second flush is a no-op', async () => {
            const row = service.buildRowForEmail(invocationWithAction('flow-1'), emailParams())!
            service.queueInvocationResults([resultWith([row])])

            await service.flush()
            expect(outputs.produce).toHaveBeenCalledTimes(1)

            await service.flush()
            expect(outputs.produce).toHaveBeenCalledTimes(1)
        })

        it('skips results that carry an empty emailAssets array', async () => {
            service.queueInvocationResults([resultWith([]), resultWith([])])
            await service.flush()
            expect(outputs.produce).not.toHaveBeenCalled()
        })

        it('rethrows on broker failure so the consumer stalls offset commit (asset rows are load-bearing)', async () => {
            const row = service.buildRowForEmail(invocationWithAction('flow-1'), emailParams())!
            const brokerDown = new Error('kafka down')
            outputs.produce.mockRejectedValueOnce(brokerDown)

            service.queueInvocationResults([resultWith([row])])

            await expect(service.flush()).rejects.toThrow(brokerDown)
        })

        it('drops the buffer on flush failure so the next flush does not re-produce the same rows (the redelivered batch supplies them again)', async () => {
            const row = service.buildRowForEmail(invocationWithAction('flow-1'), emailParams())!
            outputs.produce.mockRejectedValueOnce(new Error('kafka down'))

            service.queueInvocationResults([resultWith([row])])
            await expect(service.flush()).rejects.toThrow()

            // Second flush with no new queuing is a no-op — the same rows arrive again
            // via the redelivered Kafka offsets, not via this in-memory buffer.
            await service.flush()
            expect(outputs.produce).toHaveBeenCalledTimes(1)
        })
    })
})
