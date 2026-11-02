import { DependencyUnavailableError } from '~/common/utils/db/error'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { PubSub } from '~/common/utils/pubsub'

import { SandboxSenderStateService } from './sandbox-sender-state.service'

describe('SandboxSenderStateService', () => {
    it('rides out a transient database error instead of failing the sandbox send', async () => {
        const query = jest
            .fn()
            .mockRejectedValueOnce(
                new DependencyUnavailableError('server closed the connection unexpectedly', 'Postgres', new Error())
            )
            .mockResolvedValueOnce({ rows: [{ tenant_name: 'sandbox-tenant', sending_status: 'DISABLED' }] })
        const service = new SandboxSenderStateService(
            { query } as unknown as PostgresRouter,
            {
                on: jest.fn(),
            } as unknown as PubSub
        )

        await expect(service.isPaused('sandbox-tenant')).resolves.toBe(true)
    })
})
