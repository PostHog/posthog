import type { McpGatewayServer } from "@posthog/api-client/posthog-client";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  gateway: {} as Record<string, unknown>,
  setMemberAccess: vi.fn(),
  currentUser: null as { id: number } | null,
  refresh: vi.fn(),
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => null,
}));

vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => ({ data: mocks.currentUser }),
}));

vi.mock(
  "@posthog/ui/features/mcp-gateway/hooks/useGatewayToolPolicies",
  () => ({
    useGatewayToolPolicies: () => ({
      policies: [],
      policiesLoading: false,
      setPolicy: vi.fn(),
      setAll: vi.fn(),
      setAllPending: false,
      refresh: mocks.refresh,
      refreshPending: false,
    }),
  }),
);

vi.mock("@posthog/ui/features/mcp-gateway/hooks/useGatewayServers", () => ({
  useGatewayServers: () => mocks.gateway,
}));

vi.mock("@posthog/ui/features/mcp-gateway/hooks/useGatewayMembers", () => ({
  useGatewayMembers: () => ({
    members: [],
    membersLoading: false,
    setMemberAccess: mocks.setMemberAccess,
  }),
}));

vi.mock("@posthog/ui/features/mcp-gateway/hooks/useServiceAccounts", () => ({
  useServiceAccounts: () => ({
    accounts: [],
    accountsLoading: false,
    setAccess: vi.fn(),
    setAccessPending: false,
  }),
}));

vi.mock("@posthog/ui/features/mcp-servers/components/parts/icons", () => ({
  ServerIcon: () => <div aria-hidden="true" />,
}));

import { GatewayServerDetail } from "./GatewayServerDetail";

const server = {
  id: "server-1",
  name: "Linear",
  url: "https://mcp.linear.app",
  description: "",
  category: "productivity",
  is_team_enabled: true,
  icon_key: "",
  docs_url: "",
  template_id: null,
  template_auth_type: null,
  tool_count: 0,
  connections: [
    {
      installation_id: "installation-1",
      user: {
        id: 7,
        uuid: "user-7",
        first_name: "Ada",
        last_name: "Lovelace",
        email: "ada@example.com",
        hedgehog_config: null,
      },
      last_used_at: null,
      pending_oauth: false,
      needs_reauth: false,
    },
  ],
  your_connection: null,
  agents: [],
  revoked_user_ids: [7],
  is_revoked_for_you: false,
  created_by: null,
  created_at: "2026-07-23T12:00:00Z",
  updated_at: "2026-07-23T12:00:00Z",
} as McpGatewayServer;

describe("GatewayServerDetail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.currentUser = null;
    mocks.gateway = {
      servers: [server],
      serversLoading: false,
      templatesById: new Map(),
      connectingServerId: null,
      reconnectPending: false,
      disconnectPending: false,
      removeServerPending: false,
      connect: vi.fn(),
      reconnect: vi.fn(),
      disconnect: vi.fn(),
      toggleYourConnection: vi.fn(),
      updateServer: vi.fn(),
      removeServer: vi.fn(),
    };
  });

  it("shows revoked member access and lets an admin restore it", async () => {
    const user = userEvent.setup();
    render(
      <Theme>
        <GatewayServerDetail
          serverId={server.id}
          isAdmin
          canManageAgentAccess
          onNavigate={vi.fn()}
        />
      </Theme>,
    );

    expect(screen.getByText("Access revoked")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Revoke" }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Restore" }));

    expect(mocks.setMemberAccess).toHaveBeenCalledWith({
      userId: 7,
      serverId: server.id,
      enabled: true,
      successMessage: "Ada can now use Linear",
    });
  });

  // Members receive `connections: []` (the roster is admin-only), so the
  // delete affordance must derive from the session user, not the roster.
  it("offers a member delete on their own custom server", () => {
    mocks.currentUser = { id: 7 };
    const yourServer = {
      ...server,
      connections: [],
      revoked_user_ids: [],
      created_by: {
        id: 7,
        uuid: "user-7",
        email: "ada@example.com",
        hedgehog_config: null,
      },
      your_connection: {
        installation_id: "installation-1",
        is_enabled: true,
        pending_oauth: false,
        needs_reauth: false,
        last_used_at: null,
      },
    } as McpGatewayServer;
    mocks.gateway = { ...mocks.gateway, servers: [yourServer] };

    render(
      <Theme>
        <GatewayServerDetail
          serverId={yourServer.id}
          isAdmin={false}
          canManageAgentAccess={false}
          onNavigate={vi.fn()}
        />
      </Theme>,
    );

    expect(
      screen.getByRole("button", { name: "Delete server" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Disconnect/ }),
    ).not.toBeInTheDocument();
  });

  it("shows a single scope-aware bulk trio when a member views an agent scope", () => {
    const serverWithAgent = {
      ...server,
      agents: [
        {
          service_account_id: "sa-1",
          name: "Deploy bot",
          handle: "deploy-bot",
          status: "active",
          last_active_at: null,
          granted_by: null,
        },
      ],
    } as McpGatewayServer;
    mocks.gateway.servers = [serverWithAgent];

    render(
      <Theme>
        <GatewayServerDetail
          serverId={server.id}
          initialScope={{
            scopeType: "agent",
            scopeServiceAccountId: "sa-1",
            label: "Deploy bot",
          }}
          isAdmin={false}
          canManageAgentAccess
          onNavigate={vi.fn()}
        />
      </Theme>,
    );

    // The scope switcher carries the only bulk trio; the top-level one
    // (label "Set all") must not render alongside it.
    expect(screen.getByText("Set all for Deploy bot")).toBeInTheDocument();
    expect(screen.queryByText("Set all")).not.toBeInTheDocument();
  });

  it("collects credentials before connecting a custom server", async () => {
    const user = userEvent.setup();
    render(
      <Theme>
        <GatewayServerDetail
          serverId={server.id}
          isAdmin
          canManageAgentAccess
          onNavigate={vi.fn()}
        />
      </Theme>,
    );

    // Custom servers have no fixed auth mechanism, so connecting must ask
    // instead of assuming OAuth.
    await user.click(
      screen.getByRole("button", { name: "Connect your account" }),
    );
    expect(mocks.gateway.connect).not.toHaveBeenCalled();
    expect(screen.getByText("Authentication")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Connect" }));

    expect(mocks.gateway.connect).toHaveBeenCalledWith({
      server,
      credentials: {
        authType: "oauth",
        apiKey: "",
        clientId: "",
        clientSecret: "",
      },
    });
  });

  it("lets a connected plain member refresh tools", async () => {
    const connectedServer = {
      ...server,
      your_connection: {
        installation_id: "installation-2",
        is_enabled: true,
        pending_oauth: false,
        needs_reauth: false,
        last_used_at: null,
      },
    } as McpGatewayServer;
    mocks.gateway.servers = [connectedServer];

    const user = userEvent.setup();
    render(
      <Theme>
        <GatewayServerDetail
          serverId={connectedServer.id}
          isAdmin={false}
          canManageAgentAccess={false}
          onNavigate={vi.fn()}
        />
      </Theme>,
    );

    await user.click(
      screen.getByRole("button", { name: "Refresh tools from server" }),
    );

    expect(mocks.refresh).toHaveBeenCalledWith("installation-2");
  });
});
