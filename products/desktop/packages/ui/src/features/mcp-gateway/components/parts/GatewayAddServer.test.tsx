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

describe("GatewayAddServer", () => {
  it("keeps team and agent sharing without offering shared credentials", () => {
    render(
      <Theme>
        <GatewayAddServer isAdmin canManageAgentAccess onNavigate={vi.fn()} />
      </Theme>,
    );

    expect(
      screen.getByText("Enabled for your organization"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Who can use this connection?"),
    ).toBeInTheDocument();
    expect(screen.getByText("Everyone in this project")).toBeInTheDocument();
    expect(screen.getByText("Only me")).toBeInTheDocument();
    expect(screen.queryByText("One shared credential")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Allow personal connections"),
    ).not.toBeInTheDocument();
  });
});
