/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type {
    ConnectionStateEnumApi,
    MCPServiceAccountApi,
    MCPServiceAccountServerApi,
} from 'products/mcp_store/frontend/generated/api.schemas'

import { scoutMcpServersLogic } from './scoutMcpServersLogic'

function server(id: string, name: string, connectionState: ConnectionStateEnumApi): MCPServiceAccountServerApi {
    return {
        id,
        name,
        description: `${name} workspace`,
        icon_key: name.toLowerCase(),
        icon_domain: `${name.toLowerCase()}.com`,
        connection_state: connectionState,
    }
}

function account(
    agentKey: MCPServiceAccountApi['agent_key'],
    servers: MCPServiceAccountServerApi[],
    {
        status = 'active',
        productEnabled = true,
    }: {
        status?: MCPServiceAccountApi['status']
        productEnabled?: boolean
    } = {}
): MCPServiceAccountApi {
    return {
        id: `${agentKey}-id`,
        name: agentKey,
        description: `${agentKey} agent`,
        handle: `svc-${agentKey}`,
        agent_key: agentKey,
        status,
        product_enabled: productEnabled,
        product_disabled_reason: '',
        server_ids: servers.map(({ id }) => id),
        servers,
        last_active_at: null,
        created_at: '2026-07-22T00:00:00Z',
        updated_at: '2026-07-22T00:00:00Z',
    }
}

describe('scoutMcpServersLogic', () => {
    let logic: ReturnType<typeof scoutMcpServersLogic.build> | undefined

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('shows Scout grants and separates servers that still need setup', async () => {
        const notion = server('notion-id', 'Notion', 'missing_credential')
        const linear = server('linear-id', 'Linear', 'ready')
        const zendesk = server('zendesk-id', 'Zendesk', 'ready')
        useMocks({
            get: {
                '/api/projects/:team_id/mcp_gateway/service_accounts/': () => [
                    200,
                    {
                        count: 2,
                        next: null,
                        previous: null,
                        results: [account('support', [zendesk]), account('scout', [notion, linear])],
                    },
                ],
            },
        })

        logic = scoutMcpServersLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.scoutServers).toEqual([notion, linear])
        expect(logic.values.isScoutMcpAccessEnabled).toBe(true)
        expect(logic.values.readyScoutServers).toEqual([linear])
        expect(logic.values.availableScoutServers).toEqual([linear])
        expect(logic.values.scoutServersNeedingSetup).toEqual([notion])
    })

    it.each([
        ['MCP access is paused', { status: 'paused' as const }],
        ['Scout is unavailable', { productEnabled: false }],
    ])('does not expose ready servers when %s', async (_, accountOptions) => {
        const linear = server('linear-id', 'Linear', 'ready')
        useMocks({
            get: {
                '/api/projects/:team_id/mcp_gateway/service_accounts/': () => [
                    200,
                    {
                        count: 1,
                        next: null,
                        previous: null,
                        results: [account('scout', [linear], accountOptions)],
                    },
                ],
            },
        })

        logic = scoutMcpServersLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.scoutServers).toEqual([linear])
        expect(logic.values.isScoutMcpAccessEnabled).toBe(false)
        expect(logic.values.readyScoutServers).toEqual([linear])
        expect(logic.values.availableScoutServers).toEqual([])
        expect(logic.values.scoutServersNeedingSetup).toEqual([])
    })
})
