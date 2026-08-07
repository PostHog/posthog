import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  compilePostHogExecPermissionRegex,
  DEFAULT_POSTHOG_EXEC_PERMISSION_REGEX_SOURCE,
} from "../../../posthog-exec-permission";
import {
  clearMcpToolMetadataCache,
  setMcpToolApprovalStates,
} from "../mcp/tool-metadata";
import { canUseTool } from "./permission-handlers";

const posthogExecPermissionRegex = compilePostHogExecPermissionRegex(
  DEFAULT_POSTHOG_EXEC_PERMISSION_REGEX_SOURCE,
);

function createClient(response: Record<string, unknown>) {
  return {
    sessionUpdate: vi.fn().mockResolvedValue(undefined),
    requestPermission: vi.fn().mockResolvedValue(response),
  };
}

function createContext(
  toolName: string,
  overrides: Record<string, unknown> = {},
) {
  return {
    session: {
      permissionMode: "default" as const,
      cloudMode: false,
      settingsManager: {
        getRepoRoot: vi.fn().mockReturnValue("/repo"),
      },
      ...((overrides.session as Record<string, unknown>) ?? {}),
    },
    toolName,
    toolInput: {},
    toolUseID: "test-tool-use-id",
    suggestions: undefined,
    signal: undefined,
    client: createClient({
      outcome: { outcome: "selected", optionId: "allow" },
    }),
    sessionId: "test-session",
    fileContentCache: {},
    logger: {
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
      debug: vi.fn(),
    },
    updateConfigOption: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  } as unknown as Parameters<typeof canUseTool>[0];
}

describe("canUseTool MCP approval enforcement", () => {
  beforeEach(() => {
    clearMcpToolMetadataCache();
  });

  it("denies do_not_use MCP tools with correct message", async () => {
    setMcpToolApprovalStates({
      mcp__server__blocked_tool: "do_not_use",
    });

    const result = await canUseTool(createContext("mcp__server__blocked_tool"));

    expect(result.behavior).toBe("deny");
    if (result.behavior === "deny") {
      expect(result.message).toContain("Settings > MCP Servers");
      expect(result.message).toContain("PostHog");
      expect(result.interrupt).toBe(false);
    }
  });

  it("routes needs_approval MCP tools to permission dialog with descriptive title", async () => {
    setMcpToolApprovalStates({
      mcp__HubSpot__search_crm_objects: "needs_approval",
    });

    const context = createContext("mcp__HubSpot__search_crm_objects");
    const result = await canUseTool(context);

    expect(result.behavior).toBe("allow");
    expect(context.client.requestPermission).toHaveBeenCalledWith(
      expect.objectContaining({
        toolCall: expect.objectContaining({
          title: "The agent wants to call search_crm_objects (HubSpot)",
        }),
      }),
    );
  });

  it("allows approved MCP tools through normal flow", async () => {
    setMcpToolApprovalStates({
      mcp__server__approved_tool: "approved",
    });

    const result = await canUseTool(
      createContext("mcp__server__approved_tool"),
    );

    // Approved falls through to isToolAllowedForMode; MCP tools without
    // readOnly annotation are not auto-allowed, so they go to the default
    // permission flow which calls requestPermission
    expect(result.behavior).toBe("allow");
  });

  it("falls through for MCP tools with no approval state", async () => {
    const context = createContext("mcp__server__unknown_tool");
    const result = await canUseTool(context);

    // No approval state → falls through to isToolAllowedForMode → not allowed
    // in default mode → goes to default permission flow
    expect(result.behavior).toBe("allow");
    expect(context.client.requestPermission).toHaveBeenCalled();
  });

  it("auto-allows the speak narration tool without prompting", async () => {
    const context = createContext("mcp__posthog-code-tools__speak", {
      toolInput: { text: "all tests pass", kind: "done" },
    });
    const result = await canUseTool(context);

    expect(result.behavior).toBe("allow");
    expect(context.client.requestPermission).not.toHaveBeenCalled();
  });

  it("blocks speak when its approval state is do_not_use", async () => {
    setMcpToolApprovalStates({
      "mcp__posthog-code-tools__speak": "do_not_use",
    });

    const context = createContext("mcp__posthog-code-tools__speak", {
      toolInput: { text: "all tests pass", kind: "done" },
    });
    const result = await canUseTool(context);

    expect(result.behavior).toBe("deny");
    expect(context.client.requestPermission).not.toHaveBeenCalled();
  });

  it("tags MCP tools in the default permission flow with claudeCode.toolName so the renderer can show the server name and unwrap exec dispatch args", async () => {
    setMcpToolApprovalStates({ mcp__posthog__exec: "approved" });

    const context = createContext("mcp__posthog__exec", {
      toolInput: { command: "call experiment-get-all {}" },
    });
    const result = await canUseTool(context);

    expect(result.behavior).toBe("allow");
    expect(context.client.requestPermission).toHaveBeenCalledWith(
      expect.objectContaining({
        toolCall: expect.objectContaining({
          _meta: { claudeCode: { toolName: "mcp__posthog__exec" } },
        }),
      }),
    );
  });

  it("does not set claudeCode._meta on non-MCP tools in the default permission flow", async () => {
    const context = createContext("WebFetch", {
      toolInput: { url: "https://example.com" },
    });
    await canUseTool(context);

    const call = (context.client.requestPermission as ReturnType<typeof vi.fn>)
      .mock.calls[0]?.[0];
    expect(call?.toolCall?._meta).toBeUndefined();
  });

  it("blocks do_not_use even on read-only MCP tools", async () => {
    setMcpToolApprovalStates({
      mcp__server__readonly_blocked: "do_not_use",
    });

    const result = await canUseTool(
      createContext("mcp__server__readonly_blocked"),
    );

    expect(result.behavior).toBe("deny");
    if (result.behavior === "deny") {
      expect(result.message).toContain("blocked");
    }
  });

  it("blocks do_not_use even in bypassPermissions mode", async () => {
    setMcpToolApprovalStates({
      mcp__server__blocked_bypass: "do_not_use",
    });

    const result = await canUseTool(
      createContext("mcp__server__blocked_bypass", {
        session: { permissionMode: "bypassPermissions" },
      }),
    );

    expect(result.behavior).toBe("deny");
    if (result.behavior === "deny") {
      expect(result.message).toContain("blocked");
    }
  });

  it("does not affect non-MCP tools", async () => {
    const result = await canUseTool(createContext("Read"));

    // Read is in the auto-allowed set for default mode
    expect(result.behavior).toBe("allow");
  });

  it.each([
    "default",
    "acceptEdits",
    "plan",
    "auto",
    "bypassPermissions",
  ] as const)(
    "prompts for a configured PostHog exec match in cloud %s mode with a remembered choice",
    async (permissionMode) => {
      setMcpToolApprovalStates({ mcp__posthog__exec: "approved" });

      const context = createContext("mcp__posthog__exec", {
        toolInput: { command: "call notebooks-destroy {}" },
        session: {
          permissionMode,
          cloudMode: true,
          posthogExecPermissionRegex,
          settingsManager: {
            getRepoRoot: vi.fn().mockReturnValue("/repo"),
            hasPostHogExecApproval: vi.fn().mockReturnValue(false),
            addPostHogExecApproval: vi.fn(),
          },
        },
      });
      const result = await canUseTool(context);

      expect(result.behavior).toBe("allow");
      expect(context.client.requestPermission).toHaveBeenCalledWith(
        expect.objectContaining({
          options: [
            expect.objectContaining({ kind: "allow_once" }),
            expect.objectContaining({ kind: "allow_always" }),
            expect.objectContaining({ kind: "reject_once" }),
          ],
          toolCall: expect.objectContaining({
            title: "The agent wants to run `notebooks-destroy` on PostHog",
            _meta: { claudeCode: { toolName: "mcp__posthog__exec" } },
          }),
        }),
      );
    },
  );

  it.each(["auto", "bypassPermissions"] as const)(
    "keeps local %s mode hands-off for a configured PostHog exec match",
    async (permissionMode) => {
      setMcpToolApprovalStates({ mcp__posthog__exec: "approved" });

      const context = createContext("mcp__posthog__exec", {
        toolInput: { command: "call notebooks-destroy {}" },
        session: {
          permissionMode,
          cloudMode: false,
          posthogExecPermissionRegex,
          settingsManager: {
            getRepoRoot: vi.fn().mockReturnValue("/repo"),
            hasPostHogExecApproval: vi.fn().mockReturnValue(false),
            addPostHogExecApproval: vi.fn(),
          },
        },
      });

      const result = await canUseTool(context);

      expect(result.behavior).toBe("allow");
      expect(context.client.requestPermission).not.toHaveBeenCalled();
    },
  );

  it("skips the prompt for a remembered PostHog exec sub-tool", async () => {
    setMcpToolApprovalStates({ mcp__posthog__exec: "approved" });

    const context = createContext("mcp__posthog__exec", {
      toolInput: { command: "call experiment-update {}" },
      session: {
        permissionMode: "default",
        posthogExecPermissionRegex,
        settingsManager: {
          getRepoRoot: vi.fn().mockReturnValue("/repo"),
          hasPostHogExecApproval: vi.fn().mockReturnValue(true),
          addPostHogExecApproval: vi.fn(),
        },
      },
    });

    const result = await canUseTool(context);

    expect(result.behavior).toBe("allow");
    expect(context.client.requestPermission).not.toHaveBeenCalled();
  });

  it("persists a PostHog exec sub-tool selected with allow always", async () => {
    setMcpToolApprovalStates({ mcp__posthog__exec: "approved" });
    const addPostHogExecApproval = vi.fn().mockResolvedValue(undefined);

    const context = createContext("mcp__posthog__exec", {
      toolInput: { command: "call notebooks-destroy {}" },
      session: {
        permissionMode: "default",
        posthogExecPermissionRegex,
        settingsManager: {
          getRepoRoot: vi.fn().mockReturnValue("/repo"),
          hasPostHogExecApproval: vi.fn().mockReturnValue(false),
          addPostHogExecApproval,
        },
      },
      client: createClient({
        outcome: { outcome: "selected", optionId: "allow_always" },
      }),
    });

    const result = await canUseTool(context);

    expect(result.behavior).toBe("allow");
    expect(addPostHogExecApproval).toHaveBeenCalledWith("notebooks-destroy");
  });

  it("does not gate a nonmatching PostHog sub-tool", async () => {
    setMcpToolApprovalStates({ mcp__posthog__exec: "approved" });

    const context = createContext("mcp__posthog__exec", {
      toolInput: { command: "call experiment-get-all {}" },
      session: {
        permissionMode: "bypassPermissions",
        posthogExecPermissionRegex,
        settingsManager: {
          getRepoRoot: vi.fn().mockReturnValue("/repo"),
        },
      },
    });
    const result = await canUseTool(context);

    expect(result.behavior).toBe("allow");
    expect(context.client.requestPermission).not.toHaveBeenCalled();
  });

  // An explicit needs_approval MCP setting must win over every exec-gate
  // shortcut: a remembered sub-tool approval and the local hands-off modes.
  it.each([
    {
      label: "a remembered sub-tool approval",
      permissionMode: "default" as const,
      hasApproval: true,
    },
    {
      label: "local auto mode",
      permissionMode: "auto" as const,
      hasApproval: false,
    },
    {
      label: "local bypassPermissions mode",
      permissionMode: "bypassPermissions" as const,
      hasApproval: false,
    },
  ])(
    "still prompts via the MCP approval flow for a needs_approval exec tool despite $label",
    async ({ permissionMode, hasApproval }) => {
      setMcpToolApprovalStates({ mcp__posthog__exec: "needs_approval" });

      const context = createContext("mcp__posthog__exec", {
        toolInput: { command: "call notebooks-destroy {}" },
        session: {
          permissionMode,
          cloudMode: false,
          posthogExecPermissionRegex,
          settingsManager: {
            getRepoRoot: vi.fn().mockReturnValue("/repo"),
            hasPostHogExecApproval: vi.fn().mockReturnValue(hasApproval),
            addPostHogExecApproval: vi.fn(),
          },
        },
      });
      const result = await canUseTool(context);

      expect(result.behavior).toBe("allow");
      expect(context.client.requestPermission).toHaveBeenCalledWith(
        expect.objectContaining({
          toolCall: expect.objectContaining({
            title: "The agent wants to call exec (posthog)",
          }),
        }),
      );
    },
  );

  it("does not gate matching sub-tools when the regex is not configured", async () => {
    setMcpToolApprovalStates({ mcp__posthog__exec: "approved" });

    const context = createContext("mcp__posthog__exec", {
      toolInput: { command: "call experiment-delete {}" },
      session: {
        permissionMode: "bypassPermissions",
        settingsManager: {
          getRepoRoot: vi.fn().mockReturnValue("/repo"),
        },
      },
    });
    const result = await canUseTool(context);

    expect(result.behavior).toBe("allow");
    expect(context.client.requestPermission).not.toHaveBeenCalled();
  });

  it("emits tool denial notification for do_not_use", async () => {
    setMcpToolApprovalStates({
      mcp__server__denied_tool: "do_not_use",
    });

    const context = createContext("mcp__server__denied_tool");
    await canUseTool(context);

    expect(context.client.sessionUpdate).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "test-session",
        update: expect.objectContaining({
          sessionUpdate: "tool_call_update",
          toolCallId: "test-tool-use-id",
          status: "failed",
        }),
      }),
    );
  });
});

describe("canUseTool auto mode hands-off approval", () => {
  beforeEach(() => {
    clearMcpToolMetadataCache();
  });

  // Auto mode advertises hands-off approval; it must not prompt for the write
  // and shell tools that drive every real task.
  it.each(["Bash", "BashOutput", "KillShell", "Edit", "Write", "NotebookEdit"])(
    "auto-allows %s in auto mode without prompting",
    async (toolName) => {
      const context = createContext(toolName, {
        session: {
          permissionMode: "auto",
          settingsManager: {
            getRepoRoot: vi.fn().mockReturnValue("/repo"),
          },
        },
      });

      const result = await canUseTool(context);

      expect(result.behavior).toBe("allow");
      expect(context.client.requestPermission).not.toHaveBeenCalled();
    },
  );

  // Guard against the fix leaking into default mode, where these tools should
  // still go through the manual permission prompt.
  it.each(["Bash", "Edit", "Write"])(
    "still prompts for %s in default mode",
    async (toolName) => {
      const context = createContext(toolName, {
        session: {
          permissionMode: "default",
          settingsManager: {
            getRepoRoot: vi.fn().mockReturnValue("/repo"),
          },
        },
      });

      await canUseTool(context);

      expect(context.client.requestPermission).toHaveBeenCalled();
    },
  );
});

describe("AskUserQuestion cancelled outcomes", () => {
  const QUESTION_INPUT = {
    question: "Which license should I use?",
    options: [{ label: "MIT" }, { label: "Apache 2.0" }],
  };

  it("denies with the parked-question message when cancelled carries one", async () => {
    const context = createContext("AskUserQuestion", {
      toolInput: QUESTION_INPUT,
      client: {
        sessionUpdate: vi.fn().mockResolvedValue(undefined),
        requestPermission: vi.fn().mockResolvedValue({
          outcome: { outcome: "cancelled" },
          _meta: { message: "Waiting for the user to answer." },
        }),
      },
    });

    const result = await canUseTool(context);

    expect(result.behavior).toBe("deny");
    if (result.behavior === "deny") {
      expect(result.message).toBe("Waiting for the user to answer.");
    }
  });

  it("aborts the tool use on a bare cancelled outcome", async () => {
    const context = createContext("AskUserQuestion", {
      toolInput: QUESTION_INPUT,
      client: {
        sessionUpdate: vi.fn().mockResolvedValue(undefined),
        requestPermission: vi.fn().mockResolvedValue({
          outcome: { outcome: "cancelled" },
        }),
      },
    });

    await expect(canUseTool(context)).rejects.toThrow("Tool use aborted");
  });
});
