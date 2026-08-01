import { describe, expect, it } from "vitest";
import {
  mcpServersSchema,
  posthogExecPermissionRegexSchema,
  relayMcpServerNamesSchema,
  validateCommandParams,
} from "./schemas";

describe("mcpServersSchema", () => {
  it("accepts a valid HTTP server", () => {
    const result = mcpServersSchema.safeParse([
      {
        type: "http",
        name: "my-server",
        url: "https://mcp.example.com",
        headers: [{ name: "Authorization", value: "Bearer tok" }],
      },
    ]);
    expect(result.success).toBe(true);
    expect(result.data).toEqual([
      {
        type: "http",
        name: "my-server",
        url: "https://mcp.example.com",
        headers: [{ name: "Authorization", value: "Bearer tok" }],
      },
    ]);
  });

  it("accepts a valid SSE server", () => {
    const result = mcpServersSchema.safeParse([
      {
        type: "sse",
        name: "sse-server",
        url: "https://sse.example.com/events",
        headers: [],
      },
    ]);
    expect(result.success).toBe(true);
  });

  it("defaults headers to empty array when omitted", () => {
    const result = mcpServersSchema.safeParse([
      { type: "http", name: "no-headers", url: "https://example.com" },
    ]);
    expect(result.success).toBe(true);
    expect(result.data?.[0].headers).toEqual([]);
  });

  it("accepts multiple servers", () => {
    const result = mcpServersSchema.safeParse([
      { type: "http", name: "a", url: "https://a.com" },
      { type: "sse", name: "b", url: "https://b.com" },
    ]);
    expect(result.success).toBe(true);
    expect(result.data).toHaveLength(2);
  });

  it("accepts an empty array", () => {
    const result = mcpServersSchema.safeParse([]);
    expect(result.success).toBe(true);
    expect(result.data).toEqual([]);
  });

  it("rejects stdio servers", () => {
    const result = mcpServersSchema.safeParse([
      {
        type: "stdio",
        name: "local",
        command: "/usr/bin/mcp",
        args: [],
      },
    ]);
    expect(result.success).toBe(false);
  });

  it("rejects servers with no type", () => {
    const result = mcpServersSchema.safeParse([
      { name: "missing-type", url: "https://example.com" },
    ]);
    expect(result.success).toBe(false);
  });

  it("rejects servers with empty name", () => {
    const result = mcpServersSchema.safeParse([
      { type: "http", name: "", url: "https://example.com" },
    ]);
    expect(result.success).toBe(false);
  });

  it("rejects servers with invalid url", () => {
    const result = mcpServersSchema.safeParse([
      { type: "http", name: "bad-url", url: "not-a-url" },
    ]);
    expect(result.success).toBe(false);
  });

  it("rejects servers with missing url", () => {
    const result = mcpServersSchema.safeParse([
      { type: "http", name: "no-url" },
    ]);
    expect(result.success).toBe(false);
  });

  it("rejects non-array input", () => {
    expect(mcpServersSchema.safeParse("not-array").success).toBe(false);
    expect(mcpServersSchema.safeParse({}).success).toBe(false);
    expect(mcpServersSchema.safeParse(null).success).toBe(false);
  });

  it("rejects headers with missing fields", () => {
    const result = mcpServersSchema.safeParse([
      {
        type: "http",
        name: "bad-headers",
        url: "https://example.com",
        headers: [{ name: "X-Key" }],
      },
    ]);
    expect(result.success).toBe(false);
  });
});

describe("posthogExecPermissionRegexSchema", () => {
  it("accepts a valid permission regex", () => {
    expect(
      posthogExecPermissionRegexSchema.safeParse(
        "(^|-)(update|patch|delete|destroy)(-|$)",
      ).success,
    ).toBe(true);
  });

  it.each(["", "["])("rejects %j", (source) => {
    expect(posthogExecPermissionRegexSchema.safeParse(source).success).toBe(
      false,
    );
  });
});

describe("validateCommandParams", () => {
  it("accepts structured user_message content arrays", () => {
    const result = validateCommandParams("user_message", {
      content: [{ type: "text", text: "hello" }],
    });

    expect(result.success).toBe(true);
  });

  it("accepts artifact-only user_message payloads", () => {
    const result = validateCommandParams("user_message", {
      artifacts: [
        { id: "artifact-1", storage_path: "tasks/artifacts/file.pdf" },
      ],
    });

    expect(result.success).toBe(true);
  });

  it("rejects empty content array", () => {
    const result = validateCommandParams("user_message", {
      content: [],
    });

    expect(result.success).toBe(false);
  });

  it("accepts valid permission_response", () => {
    const result = validateCommandParams("permission_response", {
      requestId: "abc-123",
      optionId: "acceptEdits",
    });

    expect(result.success).toBe(true);
  });

  it("accepts permission_response with customInput", () => {
    const result = validateCommandParams("permission_response", {
      requestId: "abc-123",
      optionId: "reject_with_feedback",
      customInput: "Please change the approach",
    });

    expect(result.success).toBe(true);
  });

  it("rejects permission_response without requestId", () => {
    const result = validateCommandParams("permission_response", {
      optionId: "acceptEdits",
    });

    expect(result.success).toBe(false);
  });

  it("rejects permission_response without optionId", () => {
    const result = validateCommandParams("permission_response", {
      requestId: "abc-123",
    });

    expect(result.success).toBe(false);
  });

  it("accepts valid set_config_option", () => {
    const result = validateCommandParams("set_config_option", {
      configId: "mode",
      value: "plan",
    });

    expect(result.success).toBe(true);
  });

  it("rejects set_config_option without configId", () => {
    const result = validateCommandParams("set_config_option", {
      value: "plan",
    });

    expect(result.success).toBe(false);
  });

  it("accepts _posthog/refresh_session with mcpServers", () => {
    const result = validateCommandParams("_posthog/refresh_session", {
      mcpServers: [
        { type: "http", name: "mcp", url: "https://mcp.example.com" },
      ],
    });

    expect(result.success).toBe(true);
  });

  it("accepts posthog/refresh_session with empty mcpServers", () => {
    const result = validateCommandParams("posthog/refresh_session", {
      mcpServers: [],
    });

    expect(result.success).toBe(true);
  });

  it("accepts bare refresh_session", () => {
    const result = validateCommandParams("refresh_session", {
      mcpServers: [],
    });

    expect(result.success).toBe(true);
  });

  it("rejects refresh_session without mcpServers", () => {
    const result = validateCommandParams("_posthog/refresh_session", {});

    expect(result.success).toBe(false);
  });

  it("rejects refresh_session with invalid mcpServers entry", () => {
    const result = validateCommandParams("_posthog/refresh_session", {
      mcpServers: [{ type: "stdio", name: "bad", command: "/bin/x" }],
    });

    expect(result.success).toBe(false);
  });

  it("accepts an mcp_response carrying only a payload", () => {
    const result = validateCommandParams("_posthog/mcp_response", {
      requestId: "req-1",
      server: "slack",
      payload: { jsonrpc: "2.0", id: 1, result: {} },
    });

    expect(result.success).toBe(true);
  });

  it("accepts an mcp_response carrying only an error", () => {
    const result = validateCommandParams("mcp_response", {
      requestId: "req-1",
      server: "slack",
      error: { code: -32000, message: "boom" },
    });

    expect(result.success).toBe(true);
  });

  it("rejects an mcp_response with both payload and error", () => {
    const result = validateCommandParams("mcp_response", {
      requestId: "req-1",
      server: "slack",
      payload: { ok: true },
      error: { code: -32000, message: "boom" },
    });

    expect(result.success).toBe(false);
  });

  it("rejects an mcp_response with neither payload nor error", () => {
    const result = validateCommandParams("mcp_response", {
      requestId: "req-1",
      server: "slack",
    });

    expect(result.success).toBe(false);
  });

  it("rejects an mcp_response missing requestId or server", () => {
    expect(
      validateCommandParams("mcp_response", {
        server: "slack",
        payload: { ok: true },
      }).success,
    ).toBe(false);
    expect(
      validateCommandParams("mcp_response", {
        requestId: "req-1",
        payload: { ok: true },
      }).success,
    ).toBe(false);
  });
});

describe("relayMcpServerNamesSchema", () => {
  it("accepts a list of names and an empty list", () => {
    expect(
      relayMcpServerNamesSchema.safeParse(["slack", "linear"]).success,
    ).toBe(true);
    expect(relayMcpServerNamesSchema.safeParse([]).success).toBe(true);
  });

  it("rejects an empty-string name", () => {
    expect(relayMcpServerNamesSchema.safeParse(["slack", ""]).success).toBe(
      false,
    );
  });

  it("rejects a name longer than 64 chars", () => {
    expect(relayMcpServerNamesSchema.safeParse(["a".repeat(65)]).success).toBe(
      false,
    );
  });

  it("rejects more than 20 names", () => {
    const names = Array.from({ length: 21 }, (_, i) => `s${i}`);
    expect(relayMcpServerNamesSchema.safeParse(names).success).toBe(false);
  });
});
