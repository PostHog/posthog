/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import type {
    GatewayYourConnectionApi,
    MCPGatewayServerApi,
    MCPServiceAccountApi,
    MCPServiceAccountServerApi,
    UserBasicApi,
} from '@posthog/products-mcp-store/frontend/generated/api.schemas'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { supportMcpServersLogic } from './supportMcpServersLogic'

const YOU: UserBasicApi = {
    id: MOCK_DEFAULT_USER.id,
    uuid: MOCK_DEFAULT_USER.uuid,
    email: MOCK_DEFAULT_USER.email,
    hedgehog_config: null,
}

const TEAMMATE: UserBasicApi = {
    id: MOCK_DEFAULT_USER.id + 1,
    uuid: 'teammate-uuid',
    email: 'teammate@posthog.com',
    first_name: 'Terry',
    hedgehog_config: null,
}

const YOUR_CONNECTION: GatewayYourConnectionApi = {
    installation_id: 'installation-id',
    is_enabled: true,
    pending_oauth: false,
    needs_reauth: false,
    last_used_at: null,
}

function gatewayServer(
    id: string,
    name: string,
    {
        yourConnection = null,
        isTeamEnabled = true,
    }: { yourConnection?: GatewayYourConnectionApi | null; isTeamEnabled?: boolean } = {}
): MCPGatewayServerApi {
    return {
        id,
        name,
        url: `https://${name.toLowerCase()}.example.com/mcp`,
        description: `${name} workspace`,
        category: 'dev',
        template_auth_type: null,
        is_team_enabled: isTeamEnabled,
        icon_key: '',
        icon_domain: `${name.toLowerCase()}.com`,
        docs_url: '',
        template_id: null,
        tool_count: 3,
        connections: [],
        your_connection: yourConnection,
        agents: [],
        revoked_user_ids: [],
        is_revoked_for_you: false,
        created_by: YOU,
        created_at: '2026-08-01T00:00:00Z',
        updated_at: '2026-08-01T00:00:00Z',
    }
}

function grant(
    serverId: string,
    name: string,
    sharedBy: UserBasicApi,
    scope: MCPServiceAccountServerApi['scope']
): MCPServiceAccountServerApi {
    return {
        id: serverId,
        shared_by: sharedBy,
        scope,
        name,
        description: `${name} workspace`,
        icon_key: '',
        icon_domain: `${name.toLowerCase()}.com`,
        connection_state: 'ready',
    }
}

function account(
    agentKey: MCPServiceAccountApi['agent_key'],
    servers: MCPServiceAccountServerApi[]
): MCPServiceAccountApi {
    return {
        id: `${agentKey}-id`,
        name: `${agentKey} agent`,
        description: `${agentKey} agent`,
        handle: `posthog-${agentKey}`,
        agent_key: agentKey,
        status: 'active',
        server_ids: servers.map(({ id }) => id),
        servers,
        last_active_at: null,
        created_at: '2026-08-01T00:00:00Z',
        updated_at: '2026-08-01T00:00:00Z',
    }
}

function mockGateway(servers: MCPGatewayServerApi[], accounts: MCPServiceAccountApi[]): void {
    useMocks({
        get: {
            '/api/projects/:team_id/mcp_gateway/config/': () => [200, {}],
            '/api/projects/:team_id/mcp_gateway/servers/': () => [
                200,
                { count: servers.length, next: null, previous: null, results: servers },
            ],
            '/api/projects/:team_id/mcp_gateway/service_accounts/': () => [
                200,
                { count: accounts.length, next: null, previous: null, results: accounts },
            ],
            '/api/projects/:team_id/mcp_gateway/rules/': () => [
                200,
                { count: 0, next: null, previous: null, results: [] },
            ],
            '/api/projects/:team_id/mcp_servers/': () => [200, { count: 0, next: null, previous: null, results: [] }],
        },
    })
}

describe('supportMcpServersLogic', () => {
    let logic: ReturnType<typeof supportMcpServersLogic.build> | undefined

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('builds alphabetical rows for the support agent from connected servers and team shares only', async () => {
        // Alphabetical expectation: GitHub (teammate team share, not connected by you),
        // Linear (yours, shared team-scoped), Notion (yours, shared for your runs only).
        const notion = gatewayServer('notion-id', 'Notion', { yourConnection: YOUR_CONNECTION })
        const linear = gatewayServer('linear-id', 'Linear', { yourConnection: YOUR_CONNECTION })
        const github = gatewayServer('github-id', 'GitHub')
        // Sentry only carries a teammate's personal grant, which never backs a support reply.
        const sentry = gatewayServer('sentry-id', 'Sentry')
        // Zendesk is connected but turned off for the team by an admin.
        const zendesk = gatewayServer('zendesk-id', 'Zendesk', {
            yourConnection: YOUR_CONNECTION,
            isTeamEnabled: false,
        })
        const supportAccount = account('support', [
            grant('linear-id', 'Linear', YOU, 'team'),
            grant('notion-id', 'Notion', YOU, 'personal'),
            grant('github-id', 'GitHub', TEAMMATE, 'team'),
            grant('sentry-id', 'Sentry', TEAMMATE, 'personal'),
        ])
        // The scout account's grants must not leak into the support rows.
        const scoutAccount = account('scout', [grant('sentry-id', 'Sentry', YOU, 'team')])
        mockGateway([notion, linear, github, sentry, zendesk], [scoutAccount, supportAccount])

        logic = supportMcpServersLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.supportAccount?.id).toBe('support-id')
        expect(logic.values.supportServerRows.map(({ server }) => server.name)).toEqual(['GitHub', 'Linear', 'Notion'])
        expect(
            logic.values.supportServerRows.map(({ server, sharedWithTeamByYou }) => [server.name, sharedWithTeamByYou])
        ).toEqual([
            ['GitHub', false],
            ['Linear', true],
            ['Notion', false],
        ])
        const githubRow = logic.values.supportServerRows[0]
        expect(githubRow.share.teamSharedByOthers).toEqual([TEAMMATE])
        expect(githubRow.share.sharedByYou).toBe(false)
    })

    it('shows connected servers as not shared when the support account is missing', async () => {
        const linear = gatewayServer('linear-id', 'Linear', { yourConnection: YOUR_CONNECTION })
        mockGateway([linear], [])

        logic = supportMcpServersLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.supportAccount).toBeNull()
        expect(logic.values.supportServerRows).toHaveLength(1)
        expect(logic.values.supportServerRows[0].sharedWithTeamByYou).toBe(false)
        expect(logic.values.supportServerRows[0].yourGrantState).toBeNull()
        expect(logic.values.supportServerRows[0].shareDisabledReason).toBe(
            'The support agent is not available in this project yet'
        )
    })

    it('blocks sharing unhealthy connections but keeps existing shares removable', async () => {
        // A grant only mounts while its credential is healthy, so unhealthy connections must
        // not be shareable; a share that already exists must stay removable regardless.
        const healthy = gatewayServer('healthy-id', 'Healthy', { yourConnection: YOUR_CONNECTION })
        const midOauth = gatewayServer('oauth-id', 'MidOauth', {
            yourConnection: { ...YOUR_CONNECTION, pending_oauth: true },
        })
        const expired = gatewayServer('expired-id', 'Expired', {
            yourConnection: { ...YOUR_CONNECTION, needs_reauth: true },
        })
        const off = gatewayServer('off-id', 'TurnedOff', {
            yourConnection: { ...YOUR_CONNECTION, is_enabled: false },
        })
        const sharedButBroken = gatewayServer('shared-id', 'SharedButBroken', {
            yourConnection: { ...YOUR_CONNECTION, needs_reauth: true },
        })
        const supportAccount = account('support', [grant('shared-id', 'SharedButBroken', YOU, 'team')])
        mockGateway([healthy, midOauth, expired, off, sharedButBroken], [supportAccount])

        logic = supportMcpServersLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        const reasonByName = Object.fromEntries(
            logic.values.supportServerRows.map(({ server, shareDisabledReason }) => [server.name, shareDisabledReason])
        )
        expect(reasonByName).toEqual({
            Healthy: null,
            MidOauth: 'Finish connecting this server before sharing it with the support agent',
            Expired: 'Reconnect this server before sharing it with the support agent',
            TurnedOff: 'Your connection is turned off. Turn it on before sharing it with the support agent',
            SharedButBroken: null,
        })
    })
})
