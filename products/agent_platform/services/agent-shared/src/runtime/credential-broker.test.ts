import { MemoryCredentialBroker } from './credential-broker'

describe('MemoryCredentialBroker rollback receipts', () => {
    it('restores the previous credential without overwriting a newer refresh', async () => {
        const broker = new MemoryCredentialBroker()
        await broker.write('session', { posthog_api: { kind: 'posthog_bearer', token: 'original' } })

        const failedWrite = await broker.writeWithRollback('session', {
            posthog_api: { kind: 'posthog_bearer', token: 'failed' },
        })
        await failedWrite.rollback()
        await expect(broker.resolve('session', 'posthog_api')).resolves.toEqual({
            kind: 'posthog_bearer',
            token: 'original',
        })

        const staleRollback = await broker.writeWithRollback('session', {
            posthog_api: { kind: 'posthog_bearer', token: 'stale' },
        })
        await broker.write('session', { posthog_api: { kind: 'posthog_bearer', token: 'newer' } })
        await staleRollback.rollback()
        await expect(broker.resolve('session', 'posthog_api')).resolves.toEqual({
            kind: 'posthog_bearer',
            token: 'newer',
        })
    })
})
