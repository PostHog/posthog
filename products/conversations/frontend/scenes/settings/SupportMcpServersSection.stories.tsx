import type { Meta, StoryObj } from '@storybook/react'

import type {
    GatewayYourConnectionApi,
    MCPGatewayServerApi,
    MCPServiceAccountApi,
    MCPServiceAccountServerApi,
    UserBasicApi,
} from '@posthog/products-mcp-store/frontend/generated/api.schemas'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { SupportMcpServersSection } from './SupportMcpServersSection'

// The MCP servers card a support admin sees under Settings > Support > AI agent:
// which of their connected servers back the support agent, plus teammates' team shares.

const YOU: UserBasicApi = {
    id: 12345,
    uuid: '019f0000-0000-0000-0000-000000000001',
    email: 'you@example.com',
    first_name: 'You',
    hedgehog_config: null,
}

const TEAMMATE: UserBasicApi = {
    id: 54321,
    uuid: '019f0000-0000-0000-0000-000000000002',
    email: 'ana@example.com',
    first_name: 'Ana',
    last_name: 'Lopez',
    hedgehog_config: null,
}

const YOUR_CONNECTION: GatewayYourConnectionApi = {
    installation_id: 'installation-1',
    is_enabled: true,
    pending_oauth: false,
    needs_reauth: false,
    last_used_at: null,
}

function gatewayServer(
    id: string,
    name: string,
    iconDomain: string,
    yourConnection: GatewayYourConnectionApi | null
): MCPGatewayServerApi {
    return {
        id,
        name,
        url: `https://mcp.${iconDomain}/mcp`,
        description: `${name} workspace`,
        category: 'dev',
        template_auth_type: null,
        is_team_enabled: true,
        icon_key: '',
        icon_domain: iconDomain,
        docs_url: '',
        template_id: null,
        tool_count: 8,
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

const SUPPORT_ACCOUNT: MCPServiceAccountApi = {
    id: 'support-account-id',
    name: 'Support agent',
    description: 'Drafts grounded replies and investigates customer support tickets.',
    handle: 'posthog-support',
    agent_key: 'support',
    status: 'active',
    server_ids: ['linear-id', 'notion-id', 'github-id'],
    servers: [
        grant('linear-id', 'Linear', YOU, 'team'),
        grant('notion-id', 'Notion', YOU, 'personal'),
        grant('github-id', 'GitHub', TEAMMATE, 'team'),
    ],
    last_active_at: null,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
}

const SERVERS: MCPGatewayServerApi[] = [
    gatewayServer('notion-id', 'Notion', 'notion.so', YOUR_CONNECTION),
    gatewayServer('linear-id', 'Linear', 'linear.app', YOUR_CONNECTION),
    gatewayServer('github-id', 'GitHub', 'github.com', null),
    gatewayServer('slack-id', 'Slack', 'slack.com', YOUR_CONNECTION),
    gatewayServer('stripe-id', 'Stripe', 'stripe.com', YOUR_CONNECTION),
]

function gatewayMocks(servers: MCPGatewayServerApi[], accounts: MCPServiceAccountApi[]): Record<string, any> {
    return {
        '/api/projects/:team_id/mcp_gateway/config/': { allow_member_agent_access: true },
        '/api/projects/:team_id/mcp_gateway/servers/': {
            count: servers.length,
            next: null,
            previous: null,
            results: servers,
        },
        '/api/projects/:team_id/mcp_gateway/service_accounts/': {
            count: accounts.length,
            next: null,
            previous: null,
            results: accounts,
        },
        '/api/projects/:team_id/mcp_gateway/rules/': { count: 0, next: null, previous: null, results: [] },
        '/api/projects/:team_id/mcp_servers/': { count: 0, next: null, previous: null, results: [] },
        '/api/users/@me/': (): [number, any] => [
            200,
            { id: YOU.id, uuid: YOU.uuid, email: YOU.email, first_name: YOU.first_name },
        ],
    }
}

const meta: Meta<typeof SupportMcpServersSection> = {
    title: 'Scenes-App/Support/SupportMcpServersSection',
    component: SupportMcpServersSection,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2026-08-01',
        featureFlags: [FEATURE_FLAGS.MCP_GATEWAY],
    },
}
export default meta

type Story = StoryObj<typeof SupportMcpServersSection>

export const SharedAndUnsharedServers: Story = {
    decorators: [mswDecorator({ get: gatewayMocks(SERVERS, [SUPPORT_ACCOUNT]) })],
}

export const NoServersConnected: Story = {
    decorators: [mswDecorator({ get: gatewayMocks([], []) })],
}
