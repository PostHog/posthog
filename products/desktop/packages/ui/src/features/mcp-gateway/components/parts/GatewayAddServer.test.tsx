import type { McpServiceAccount } from "@posthog/api-client/posthog-client";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock(
  "@posthog/ui/features/mcp-gateway/hooks/useRegisterGatewayServer",
  () => ({
    useRegisterGatewayServer: () => ({
      register: vi.fn(),
      registerPending: false,
    }),
  }),
);

import { GatewayAddServer } from "./GatewayAddServer";

const account = {
  id: "agent-1",
  name: "Support agent",
  description: "",
  handle: "support-agent",
  status: "active",
  token_mask: "",
  server_ids: [],
  last_active_at: null,
  created_at: "2026-07-23T12:00:00Z",
  updated_at: "2026-07-23T12:00:00Z",
} as McpServiceAccount;

describe("GatewayAddServer", () => {
  it("keeps team and agent sharing without offering shared credentials", () => {
    render(
      <Theme>
        <GatewayAddServer
          isAdmin
          canManageAgentAccess
          accounts={[account]}
          onNavigate={vi.fn()}
        />
      </Theme>,
    );

    expect(screen.getByText("Available to team members")).toBeInTheDocument();
    expect(screen.getByText("Share with agents")).toBeInTheDocument();
    expect(screen.getByText(account.name)).toBeInTheDocument();
    expect(screen.queryByText("One shared credential")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Allow personal connections"),
    ).not.toBeInTheDocument();
  });
});
