import jwt from 'jsonwebtoken'

import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

import {
    IntegrationGatewayService,
    IntegrationGatewayServiceConfig,
    createIntegrationGatewayService,
} from './integration-gateway.service'

jest.mock('~/common/utils/request', () => ({
    ...jest.requireActual('~/common/utils/request'),
    internalFetch: jest.fn(),
}))
const mockInternalFetch = internalFetch as jest.Mock

const AUDIENCE = 'posthog:integration_gateway'

function config(rollout = '*'): IntegrationGatewayServiceConfig {
    return {
        CDP_INTEGRATION_GATEWAY_URL: 'http://gw:6738',
        CDP_INTEGRATION_GATEWAY_JWT_SECRET: 'test-secret',
        CDP_INTEGRATION_GATEWAY_ROLLOUT: rollout,
    }
}

describe('IntegrationGatewayService', () => {
    it('mints a team-scoped token, calls the gateway, and normalizes missing ids to null', async () => {
        mockInternalFetch.mockResolvedValue({
            status: 200,
            json: () =>
                Promise.resolve({
                    integrations: {
                        '1': {
                            id: 1,
                            team_id: 42,
                            kind: 'slack',
                            config: {},
                            sensitive_config: { access_token: 'tok' },
                        },
                    },
                }),
            dump: () => Promise.resolve(),
        })

        const result = await new IntegrationGatewayService(config()).fetchMany([1, 2], 42)
        expect(result['1']?.sensitive_config.access_token).toBe('tok')
        expect(result['2']).toBeNull()

        const [url, options] = mockInternalFetch.mock.calls[0]
        expect(url).toBe('http://gw:6738/api/v1/credentials/fetch')
        expect(parseJSON(options.body).integration_ids).toEqual([1, 2])
        const token = (options.headers.authorization as string).replace('Bearer ', '')
        // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
        const decoded = jwt.verify(token, 'test-secret', { audience: AUDIENCE }) as jwt.JwtPayload
        expect(decoded.team_id).toBe(42)
        expect(decoded.caller).toBe('cdp')
    })

    it('throws on a non-200 so the manager falls back to Postgres', async () => {
        mockInternalFetch.mockResolvedValue({
            status: 503,
            json: () => Promise.resolve({}),
            dump: () => Promise.resolve(),
        })
        await expect(new IntegrationGatewayService(config()).fetchMany([1], 42)).rejects.toThrow('503')
    })

    it('throws on a 200 with a malformed body so the manager falls back to Postgres', async () => {
        mockInternalFetch.mockResolvedValue({
            status: 200,
            json: () => Promise.resolve({ unexpected: true }),
            dump: () => Promise.resolve(),
        })
        await expect(new IntegrationGatewayService(config()).fetchMany([1], 42)).rejects.toThrow(/malformed/)
    })

    it.each([
        ['a specific team in the list', '42', 42, true],
        ['a team not in the list', '7', 42, false],
        ['all teams via star', '*', 42, true],
    ])('enabledForTeam gates by rollout (%s)', (_name, rollout, teamId, expected) => {
        expect(new IntegrationGatewayService(config(rollout)).enabledForTeam(teamId)).toBe(expected)
    })

    it.each([
        ['url', { CDP_INTEGRATION_GATEWAY_URL: '' }],
        ['secret', { CDP_INTEGRATION_GATEWAY_JWT_SECRET: '' }],
        ['rollout', { CDP_INTEGRATION_GATEWAY_ROLLOUT: '' }],
    ])('createIntegrationGatewayService returns null when missing %s', (_name, override) => {
        expect(createIntegrationGatewayService({ ...config(), ...override })).toBeNull()
    })

    it('createIntegrationGatewayService builds a client when fully configured', () => {
        expect(createIntegrationGatewayService(config())).toBeInstanceOf(IntegrationGatewayService)
    })
})
