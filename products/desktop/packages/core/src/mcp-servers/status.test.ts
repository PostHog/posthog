import type { McpServerInstallation } from "@posthog/api-client/types";
import { describe, expect, it } from "vitest";
import { getInstallationStatus } from "./status";

function makeInstallation(
  overrides: Partial<McpServerInstallation> = {},
): McpServerInstallation {
  return {
    id: "inst-1",
    template_id: null,
    name: "Test",
    icon_key: "",
    icon_domain: "",
    proxy_url: "https://proxy.example.com/inst-1",
    tool_count: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    needs_reauth: false,
    pending_oauth: false,
    ...overrides,
  };
}

describe("getInstallationStatus", () => {
  it("returns connected for a live installation", () => {
    expect(getInstallationStatus(makeInstallation())).toBe("connected");
  });

  it("returns pending_oauth when the OAuth flow is incomplete", () => {
    expect(
      getInstallationStatus(makeInstallation({ pending_oauth: true })),
    ).toBe("pending_oauth");
  });

  it("returns needs_reauth when the server demands re-auth", () => {
    expect(
      getInstallationStatus(makeInstallation({ needs_reauth: true })),
    ).toBe("needs_reauth");
  });

  it("prefers pending_oauth over needs_reauth if both set", () => {
    expect(
      getInstallationStatus(
        makeInstallation({ pending_oauth: true, needs_reauth: true }),
      ),
    ).toBe("pending_oauth");
  });
});
