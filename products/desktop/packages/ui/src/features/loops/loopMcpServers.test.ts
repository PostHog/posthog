import type { McpServerInstallation } from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import {
  isLoopMcpServerReady,
  selectableLoopMcpServers,
  unavailableLoopMcpServerIds,
} from "./loopMcpServers";

function installation(
  overrides: Partial<McpServerInstallation> & { id: string },
): McpServerInstallation {
  return {
    template_id: null,
    name: "Linear",
    icon_key: "",
    icon_domain: "",
    needs_reauth: false,
    pending_oauth: false,
    proxy_url: "",
    tool_count: 0,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

describe("loopMcpServers", () => {
  it("offers only personal installations, treating a missing scope as personal", () => {
    const servers = selectableLoopMcpServers([
      installation({ id: "personal", scope: "personal" }),
      installation({ id: "shared", scope: "shared" }),
      installation({ id: "unscoped" }),
    ]);
    expect(servers.map((server) => server.id)).toEqual([
      "personal",
      "unscoped",
    ]);
  });

  it("reports selected ids with no selectable connection behind them", () => {
    const selectable = [installation({ id: "kept", scope: "personal" })];
    expect(
      unavailableLoopMcpServerIds(["kept", "uninstalled"], selectable),
    ).toEqual(["uninstalled"]);
  });

  // Mirrors the backend's active-installation check: a not-ready connection
  // is rejected on save, so the picker must not offer to turn it on.
  it.each([
    { name: "enabled and connected", overrides: {}, expected: true },
    {
      name: "explicitly enabled",
      overrides: { is_enabled: true },
      expected: true,
    },
    { name: "disabled", overrides: { is_enabled: false }, expected: false },
    {
      name: "pending oauth",
      overrides: { pending_oauth: true },
      expected: false,
    },
    {
      name: "needs reauth",
      overrides: { auth_type: "oauth" as const, needs_reauth: true },
      expected: false,
    },
  ])("isLoopMcpServerReady: $name → $expected", ({ overrides, expected }) => {
    expect(isLoopMcpServerReady(installation({ id: "i1", ...overrides }))).toBe(
      expected,
    );
  });
});
