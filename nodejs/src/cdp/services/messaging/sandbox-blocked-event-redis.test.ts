import { createRedisFromConfig } from '~/common/utils/db/redis'
import { killGracefully } from '~/common/utils/utils'

import { sandboxBlockedEventRedisConfig } from './sandbox-email-sender'

jest.mock('~/common/utils/utils', () => ({
    ...jest.requireActual('~/common/utils/utils'),
    killGracefully: jest.fn(),
}))

describe('sandboxBlockedEventRedisConfig', () => {
    it('keeps the worker running when Redis refuses its connections', async () => {
        const { connection } = sandboxBlockedEventRedisConfig({
            url: '127.0.0.1',
            // More reconnect attempts than a fatal client tolerates before it stops the process.
            options: { port: 1, commandTimeout: 5000, retryStrategy: (attempt) => (attempt < 15 ? 5 : null) },
            name: 'sandbox-blocked-event-test',
        })

        await expect(createRedisFromConfig(connection)).rejects.toThrow()
        expect(killGracefully).not.toHaveBeenCalled()
    })
})
