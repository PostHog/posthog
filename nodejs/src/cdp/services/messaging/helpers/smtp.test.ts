import { createIntegration } from '~/cdp/_tests/fixtures'
import { IntegrationType } from '~/cdp/types'

import { SmtpTransportPool, smtpConfigFromIntegration } from './smtp'

const smtpIntegration = (
    config: Record<string, any> = {},
    sensitiveConfig: Record<string, any> = {}
): IntegrationType =>
    createIntegration({
        id: 1,
        kind: 'email',
        config: {
            email: 'sender@example.com',
            name: 'Sender',
            provider: 'smtp',
            host: 'localhost',
            port: 2525,
            encryption: 'none',
            verified: true,
            ...config,
        },
        sensitive_config: sensitiveConfig,
    })

describe('smtp helpers', () => {
    describe('smtpConfigFromIntegration', () => {
        it('maps config and sensitive_config into a connection config', () => {
            expect(smtpConfigFromIntegration(smtpIntegration({ username: 'apikey' }, { password: 'secret' }))).toEqual({
                host: 'localhost',
                port: 2525,
                encryption: 'none',
                username: 'apikey',
                password: 'secret',
            })
        })

        it.each([
            ['missing host', { host: '' }, /no host configured/],
            // Port 25 must stay blocked even if a row is hand-crafted past the API validation
            ['port 25', { port: 25 }, /port must be one of/],
            ['arbitrary port', { port: 8025 }, /port must be one of/],
            ['unknown encryption mode', { encryption: 'tls' }, /invalid encryption mode/],
        ])('rejects an integration with %s', (_name, overrides, expectedError) => {
            expect(() => smtpConfigFromIntegration(smtpIntegration(overrides))).toThrow(expectedError)
        })
    })

    describe('SmtpTransportPool', () => {
        let pool: SmtpTransportPool

        beforeEach(() => {
            pool = new SmtpTransportPool()
        })

        afterEach(() => {
            pool.closeAll()
        })

        it('reuses the pooled transport for an unchanged config', async () => {
            const integration = smtpIntegration({ username: 'apikey' }, { password: 'secret' })
            const first = await pool.get(integration)
            const second = await pool.get(integration)
            expect(second).toBe(first)
        })

        it('rebuilds the transport when the password rotates, closing the old one', async () => {
            // Regression: a cached transport with stale credentials would keep failing sends
            // after the user fixes their password, until the worker restarts.
            const first = await pool.get(smtpIntegration({ username: 'apikey' }, { password: 'old-secret' }))
            const closeSpy = jest.spyOn(first, 'close')

            const second = await pool.get(smtpIntegration({ username: 'apikey' }, { password: 'new-secret' }))

            expect(second).not.toBe(first)
            expect(closeSpy).toHaveBeenCalled()
        })
    })
})
