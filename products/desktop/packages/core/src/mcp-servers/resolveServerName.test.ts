import type {
  McpRecommendedServer,
  McpServerInstallation,
} from "@posthog/api-client/types";
import { describe, expect, it } from "vitest";
import {
  resolveServerDetails,
  resolveServerName,
  sortInstallationsByName,
} from "./resolveServerName";

function installation(
  overrides: Partial<McpServerInstallation> = {},
): McpServerInstallation {
  return {
    id: "inst-1",
    template_id: null,
    name: "",
    icon_domain: "",
    proxy_url: "https://proxy.example.com/inst-1",
    tool_count: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    needs_reauth: false,
    pending_oauth: false,
    ...overrides,
  } as McpServerInstallation;
}

function template(
  overrides: Partial<McpRecommendedServer>,
): McpRecommendedServer {
  return {
    id: "tpl-1",
    name: "Template",
    url: "https://example.com/mcp",
    description: "",
    auth_type: "oauth",
    ...overrides,
  } as McpRecommendedServer;
}

describe("resolveServerName", () => {
  it("prefers display_name, then name, then template name, then url", () => {
    expect(
      resolveServerName(installation({ display_name: "D", name: "N" }), null),
    ).toBe("D");
    expect(resolveServerName(installation({ name: "N" }), null)).toBe("N");
    expect(resolveServerName(installation({}), template({ name: "T" }))).toBe(
      "T",
    );
    expect(resolveServerName(installation({ url: "https://u" }), null)).toBe(
      "https://u",
    );
    expect(resolveServerName(installation({}), null)).toBe("Server");
  });
});

describe("resolveServerDetails", () => {
  it("resolves description/docs/icon/auth fallbacks", () => {
    const out = resolveServerDetails(
      installation({
        name: "N",
        icon_domain: "",
        url: "https://mcp.acme.dev/mcp",
      }),
      template({
        description: "desc",
        docs_url: "https://docs",
        icon_domain: "linear.app",
      }),
    );
    expect(out.name).toBe("N");
    expect(out.description).toBe("desc");
    expect(out.docsUrl).toBe("https://docs");
    expect(out.iconDomain).toBe("linear.app");
    expect(out.serverUrl).toBe("https://mcp.acme.dev/mcp");
    expect(out.authType).toBe("oauth");
  });

  it("falls back to the template url when the installation has none", () => {
    const out = resolveServerDetails(
      null,
      template({ icon_domain: "", url: "https://mcp.linear.app/sse" }),
    );
    expect(out.iconDomain).toBeNull();
    expect(out.serverUrl).toBe("https://mcp.linear.app/sse");
  });
});

describe("sortInstallationsByName", () => {
  it("sorts case-insensitively by resolved name", () => {
    const map = new Map<string, McpRecommendedServer>();
    const out = sortInstallationsByName(
      [
        installation({ id: "1", display_name: "banana" }),
        installation({ id: "2", display_name: "Apple" }),
      ],
      map,
    );
    expect(out.map((i) => i.id)).toEqual(["2", "1"]);
  });
});
