import type { McpServerInstallation } from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import {
  isLoopMcpServerReady,
  selectableLoopMcpServers,
  unavailableLoopMcpServerIds,
  visibleLoopMcpServers,
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

  // A not-ready connection can never be newly selected, so the picker hides
  // it unless it's already selected: then it must stay visible so the user
  // can unselect it instead of being blocked by an invisible id on save.
  it("shows ready servers plus selected not-ready ones, hiding the rest", () => {
    const servers = visibleLoopMcpServers(
      [
        installation({ id: "ready" }),
        installation({ id: "disabled-selected", is_enabled: false }),
        installation({ id: "disabled-unselected", is_enabled: false }),
        installation({ id: "reauth-unselected", needs_reauth: true }),
        installation({ id: "shared-selected", scope: "shared" }),
      ],
      ["disabled-selected", "shared-selected"],
    );
    expect(servers.map((server) => server.id)).toEqual([
      "ready",
      "disabled-selected",
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
