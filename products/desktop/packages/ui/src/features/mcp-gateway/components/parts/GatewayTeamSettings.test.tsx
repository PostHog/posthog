import type {
  McpGatewayServer,
  McpRecommendedServer,
} from "@posthog/api-client/posthog-client";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  servers: [] as McpGatewayServer[],
  recommendedTemplates: [] as McpRecommendedServer[],
  defaultServersEnabled: true,
  updateServer: vi.fn(),
  setTemplateEnabled: vi.fn(),
  setAllEnabled: vi.fn(),
}));

vi.mock("@posthog/ui/features/mcp-gateway/hooks/useGatewayConfig", () => ({
  useGatewayConfig: () => ({
    allowCustomServers: true,
    allowMemberAgentAccess: true,
    defaultServersEnabled: mocks.defaultServersEnabled,
    updateSettings: vi.fn(),
  }),
}));

vi.mock("@posthog/ui/features/mcp-gateway/hooks/useGatewayServers", () => ({
  useGatewayServers: () => ({
    servers: mocks.servers,
    recommendedTemplates: mocks.recommendedTemplates,
    updateServer: mocks.updateServer,
    setTemplateEnabled: mocks.setTemplateEnabled,
    setAllEnabled: mocks.setAllEnabled,
    setAllEnabledPending: false,
  }),
}));

vi.mock("@posthog/ui/features/mcp-servers/components/parts/icons", () => ({
  ServerIcon: () => <div aria-hidden="true" />,
}));

import { GatewayTeamSettings } from "./GatewayTeamSettings";

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
  connections: [],
  your_connection: null,
  agents: [],
  revoked_user_ids: [],
  is_revoked_for_you: false,
  created_by: null,
  created_at: "2026-07-23T12:00:00Z",
  updated_at: "2026-07-23T12:00:00Z",
} as McpGatewayServer;

const template = {
  id: "template-1",
  name: "Stripe",
  url: "https://mcp.stripe.com",
  icon_key: "",
  icon_domain: "stripe.com",
} as McpRecommendedServer;

describe("GatewayTeamSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.servers = [server];
    mocks.recommendedTemplates = [template];
    mocks.defaultServersEnabled = true;
  });

  it("opens a server detail page from the server access list", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();

    render(
      <Theme>
        <GatewayTeamSettings onNavigate={onNavigate} />
      </Theme>,
    );

    await user.click(screen.getByRole("button", { name: /Linear/ }));

    expect(onNavigate).toHaveBeenCalledWith({
      view: "server",
      serverId: server.id,
    });
  });

  it("counts untouched catalog templates in the merged access list", () => {
    render(
      <Theme>
        <GatewayTeamSettings onNavigate={vi.fn()} />
      </Theme>,
    );

    expect(screen.getByText("2 of 2 servers enabled")).toBeInTheDocument();
    expect(screen.getByText("Stripe")).toBeInTheDocument();
  });

  it("toggles an untouched template via set_template_enabled, not PATCH", async () => {
    const user = userEvent.setup();

    render(
      <Theme>
        <GatewayTeamSettings onNavigate={vi.fn()} />
      </Theme>,
    );

    const switches = screen.getAllByRole("switch");
    // Rows sort by name: Linear (server) before Stripe (template); the first
    // two switches are the top-level settings toggles.
    await user.click(switches[switches.length - 1]);

    expect(mocks.setTemplateEnabled).toHaveBeenCalledWith(
      { templateId: template.id, enabled: false },
      expect.anything(),
    );
    expect(mocks.updateServer).not.toHaveBeenCalled();
  });

  it("counts templates as disabled when the team default is off", () => {
    mocks.defaultServersEnabled = false;

    render(
      <Theme>
        <GatewayTeamSettings onNavigate={vi.fn()} />
      </Theme>,
    );

    expect(screen.getByText("1 of 2 servers enabled")).toBeInTheDocument();
  });

  it("uses the bulk endpoint for disable all", async () => {
    const user = userEvent.setup();

    render(
      <Theme>
        <GatewayTeamSettings onNavigate={vi.fn()} />
      </Theme>,
    );

    await user.click(screen.getByRole("button", { name: /Disable all/ }));

    expect(mocks.setAllEnabled).toHaveBeenCalledWith(false);
    expect(mocks.updateServer).not.toHaveBeenCalled();
  });
});
