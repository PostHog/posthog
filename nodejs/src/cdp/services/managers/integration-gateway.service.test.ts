import jwt from 'jsonwebtoken'

import { PosthogJwtAudience } from '~/cdp/utils/jwt-utils'
import { internalFetch } from '~/common/utils/request'

import {
    createIntegrationGatewayService,
    IntegrationGatewayConfig,
    IntegrationGatewayService,
} from './integration-gateway.service'

jest.mock('~/common/utils/request', () => ({
    ...jest.requireActual('~/common/utils/request'),
    internalFetch: jest.fn(),
}))

const mockInternalFetch = internalFetch as jest.Mock

const config = (rollout: string): IntegrationGatewayConfig => ({
    CDP_INTEGRATION_GATEWAY_URL: 'http://gw:3350',
    CDP_INTEGRATION_GATEWAY_JWT_SECRET: 'test-secret',
    CDP_INTEGRATION_GATEWAY_ROLLOUT: rollout,
})

describe('IntegrationGatewayService', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    describe('createIntegrationGatewayService', () => {
        it('returns null when disabled or unconfigured', () => {
            expect(createIntegrationGatewayService(config(''))).toBeNull()
            expect(createIntegrationGatewayService({ ...config('*'), CDP_INTEGRATION_GATEWAY_URL: '' })).toBeNull()
            expect(createIntegrationGatewayService({ ...config('*'), CDP_INTEGRATION_GATEWAY_JWT_SECRET: '' })).toBeNull()
        })

        it('builds a service when url + secret + rollout are set', () => {
            expect(createIntegrationGatewayService(config('*'))).toBeInstanceOf(IntegrationGatewayService)
        })
    })

    describe('enabledForTeam', () => {
        it('honors team-id and percentage rollout strings', () => {
            expect(new IntegrationGatewayService(config('123')).enabledForTeam(123)).toBe(true)
            expect(new IntegrationGatewayService(config('123')).enabledForTeam(456)).toBe(false)
            expect(new IntegrationGatewayService(config('*')).enabledForTeam(999)).toBe(true)
            expect(new IntegrationGatewayService(config('')).enabledForTeam(1)).toBe(false)
        })
    })

    describe('fetchMany', () => {
        it('mints a team-scoped token and normalizes missing ids to null', async () => {
            mockInternalFetch.mockResolvedValue({
                status: 200,
                json: async () => ({
                    integrations: {
                        '1': { id: 1, team_id: 42, kind: 'slack', config: {}, sensitive_config: { access_token: 'tok' } },
                    },
                }),
                dump: async () => {},
            })

            const result = await new IntegrationGatewayService(config('*')).fetchMany([1, 2], 42)

            expect(result['1']?.sensitive_config.access_token).toBe('tok')
            // id 2 wasn't returned by the gateway -> normalized to null (not undefined/missing)
            expect(result['2']).toBeNull()

            const [url, opts] = mockInternalFetch.mock.calls[0]
            expect(url).toBe('http://gw:3350/api/v1/credentials/fetch')
            expect(JSON.parse(opts.body)).toEqual({ integration_ids: [1, 2] })

            const token = (opts.headers.Authorization as string).replace('Bearer ', '')
            const decoded = jwt.verify(token, 'test-secret', {
                audience: PosthogJwtAudience.INTEGRATION_GATEWAY,
            }) as jwt.JwtPayload
            expect(decoded.team_id).toBe(42)
            expect(decoded.caller).toBe('cdp')
        })

        it('throws on a non-200 so the manager falls back to Postgres', async () => {
            mockInternalFetch.mockResolvedValue({ status: 503, json: async () => ({}), dump: async () => {} })
            await expect(new IntegrationGatewayService(config('*')).fetchMany([1], 42)).rejects.toThrow('503')
        })
    })
})
