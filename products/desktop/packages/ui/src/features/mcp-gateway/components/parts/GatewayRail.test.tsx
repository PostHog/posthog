import type { McpGatewayServer } from "@posthog/api-client/posthog-client";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GatewayRail } from "./GatewayRail";

vi.mock("@posthog/ui/features/mcp-servers/components/parts/icons", () => ({
  ServerIcon: () => <div aria-hidden="true" />,
}));

function server(overrides: Partial<McpGatewayServer> = {}): McpGatewayServer {
  return {
    id: "srv-1",
    name: "Notion",
    url: "https://mcp.example.com",
    description: "",
    category: "dev",
    is_team_enabled: true,
    icon_key: "",
    docs_url: "",
    template_id: null,
    template_auth_type: null,
    tool_count: 0,
    connections: [],
    your_connection: null,
    agents: [],
    revoked_user_ids: [],
    is_revoked_for_you: false,
    created_by: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function renderRail(servers: McpGatewayServer[]) {
  return render(
    <Theme>
      <GatewayRail
        servers={servers}
        templatesById={new Map()}
        isAdmin={false}
        canAddServers={false}
        route={{ view: "servers" }}
        onNavigate={vi.fn()}
      />
    </Theme>,
  );
}

describe("GatewayRail", () => {
  it("lists a server the caller has connected", () => {
    renderRail([
      server({
        your_connection: {
          installation_id: "inst-1",
          is_enabled: true,
          pending_oauth: false,
          needs_reauth: false,
          last_used_at: null,
        },
      }),
    ]);

    expect(screen.getByText("Notion")).toBeInTheDocument();
    expect(screen.queryByText("No connections yet.")).not.toBeInTheDocument();
  });

  it("shows the empty state for a server the caller has not connected", () => {
    renderRail([server()]);

    expect(screen.queryByText("Notion")).not.toBeInTheDocument();
    expect(screen.getByText("No connections yet.")).toBeInTheDocument();
  });

  it.each([
    [
      "self-disabled",
      server({
        your_connection: {
          installation_id: "inst-1",
          is_enabled: false,
          pending_oauth: false,
          needs_reauth: false,
          last_used_at: "2026-01-01T00:00:00Z",
        },
      }),
      "Disabled for you",
    ],
    [
      "team-disabled",
      server({
        is_team_enabled: false,
        your_connection: {
          installation_id: "inst-1",
          is_enabled: true,
          pending_oauth: false,
          needs_reauth: false,
          last_used_at: "2026-01-01T00:00:00Z",
        },
      }),
      "Off for the team",
    ],
    [
      "revoked",
      server({
        is_revoked_for_you: true,
        your_connection: {
          installation_id: "inst-1",
          is_enabled: true,
          pending_oauth: false,
          needs_reauth: false,
          last_used_at: "2026-01-01T00:00:00Z",
        },
      }),
      "Access revoked",
    ],
  ] as const)(
    "labels a %s server instead of showing it as connected",
    (_label, srv, expected) => {
      renderRail([srv]);

      expect(screen.getByText(expected)).toBeInTheDocument();
      expect(screen.queryByText(/used .* ago/)).not.toBeInTheDocument();
    },
  );
});
