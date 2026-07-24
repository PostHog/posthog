import type { HookInput } from "@anthropic-ai/claude-agent-sdk";
import { describe, expect, test, vi } from "vitest";
import type { FileEnrichmentDeps } from "../../enrichment/file-enricher";

const enrichFileMock = vi.hoisted(() => vi.fn());
vi.mock("../../enrichment/file-enricher", () => ({
  enrichFileForAgent: enrichFileMock,
}));

import { Logger } from "../../utils/logger";
import type { TaskState } from "./conversion/task-state";
import {
  createPreToolUseHook,
  createReadEnrichmentHook,
  createReadImageGuardHook,
  createSignedCommitGuardHook,
  createTaskHook,
  type EnrichedReadCache,
} from "./hooks";
import type {
  PermissionCheckResult,
  SettingsManager,
} from "./session/settings";

const stubDeps = {} as FileEnrichmentDeps;

function buildReadHookInput(
  overrides: Partial<HookInput> & {
    file_path?: string;
    tool_response?: unknown;
  } = {},
): HookInput {
  return {
    session_id: "test-session",
    transcript_path: "/tmp/transcript",
    cwd: "/tmp",
    hook_event_name: "PostToolUse",
    tool_name: "Read",
    tool_use_id: "toolu_1",
    tool_input: { file_path: overrides.file_path ?? "/tmp/code.ts" },
    tool_response: overrides.tool_response ?? "raw-content",
    ...overrides,
  } as HookInput;
}

describe("createReadImageGuardHook", () => {
  test.each([
    {
      name: "unsupported image type",
      image: {
        type: "image",
        source: {
          type: "base64",
          media_type: "image/heic",
          data: "ZmFrZQ==",
        },
      },
      expectedReason: "unsupported image type image/heic",
    },
    {
      name: "oversized image",
      image: {
        type: "image",
        source: {
          type: "base64",
          media_type: "image/png",
          data: "A".repeat((6 * 1024 * 1024 * 4) / 3),
        },
      },
      expectedReason: "5 MB per-image limit",
    },
    {
      name: "empty image data",
      image: {
        type: "image",
        source: {
          type: "base64",
          media_type: "image/png",
          data: "",
        },
      },
      expectedReason: "image data is empty",
    },
  ])(
    "replaces a $name before it reaches the model",
    async ({ image, expectedReason }) => {
      const hook = createReadImageGuardHook();
      const result = await hook(
        buildReadHookInput({
          tool_response: {
            content: [{ type: "text", text: "Image Size: 1200x800." }, image],
          },
        }),
        undefined,
        { signal: new AbortController().signal },
      );

      expect(result).toMatchObject({
        continue: true,
        hookSpecificOutput: {
          hookEventName: "PostToolUse",
          updatedToolOutput: {
            content: [
              { type: "text", text: "Image Size: 1200x800." },
              { type: "text", text: expect.stringContaining(expectedReason) },
            ],
          },
        },
      });
    },
  );

  test("wraps sanitized bare content arrays as a Read tool result", async () => {
    const hook = createReadImageGuardHook();
    const result = await hook(
      buildReadHookInput({
        tool_response: [
          {
            type: "image",
            source: {
              type: "base64",
              media_type: "image/heic",
              data: "ZmFrZQ==",
            },
          },
        ],
      }),
      undefined,
      { signal: new AbortController().signal },
    );

    expect(result).toEqual({
      continue: true,
      hookSpecificOutput: {
        hookEventName: "PostToolUse",
        updatedToolOutput: {
          content: [
            {
              type: "text",
              text: "[Removed unprocessable image: unsupported image type image/heic]",
            },
          ],
        },
      },
    });
  });

  test("leaves supported images unchanged", async () => {
    const hook = createReadImageGuardHook();
    const result = await hook(
      buildReadHookInput({
        tool_response: [
          {
            type: "image",
            source: {
              type: "base64",
              media_type: "image/png",
              data: "ZmFrZQ==",
            },
          },
        ],
      }),
      undefined,
      { signal: new AbortController().signal },
    );

    expect(result).toEqual({ continue: true });
  });
});

describe("createReadEnrichmentHook", () => {
  test("returns { continue: true } for non-PostToolUse events", async () => {
    enrichFileMock.mockReset();
    const cache: EnrichedReadCache = new Map();
    const hook = createReadEnrichmentHook(stubDeps, cache);
    const result = await hook(
      { hook_event_name: "PreToolUse" } as HookInput,
      undefined,
      { signal: new AbortController().signal },
    );
    expect(result).toEqual({ continue: true });
    expect(enrichFileMock).not.toHaveBeenCalled();
  });

  test("returns { continue: true } for non-Read tools", async () => {
    enrichFileMock.mockReset();
    const cache: EnrichedReadCache = new Map();
    const hook = createReadEnrichmentHook(stubDeps, cache);
    const result = await hook(
      buildReadHookInput({ tool_name: "Bash" }),
      undefined,
      { signal: new AbortController().signal },
    );
    expect(result).toEqual({ continue: true });
    expect(enrichFileMock).not.toHaveBeenCalled();
  });

  test("passes stripped content and file_path into enricher", async () => {
    enrichFileMock.mockReset();
    enrichFileMock.mockResolvedValueOnce(null);

    const cache: EnrichedReadCache = new Map();
    const hook = createReadEnrichmentHook(stubDeps, cache);
    await hook(
      buildReadHookInput({
        file_path: "/tmp/app.ts",
        tool_response: "     1\tconst x = 1;\n     2\tposthog.capture('x');",
      }),
      undefined,
      { signal: new AbortController().signal },
    );

    expect(enrichFileMock).toHaveBeenCalledTimes(1);
    const [, filePath, content] = enrichFileMock.mock.calls[0];
    expect(filePath).toBe("/tmp/app.ts");
    expect(content).toBe("const x = 1;\nposthog.capture('x');");
  });

  test("returns additionalContext when enricher produces annotations", async () => {
    enrichFileMock.mockReset();
    enrichFileMock.mockResolvedValueOnce(
      "posthog.capture('x'); // [PostHog] Event: \"x\"",
    );

    const cache: EnrichedReadCache = new Map();
    const hook = createReadEnrichmentHook(stubDeps, cache);
    const result = await hook(
      buildReadHookInput({ file_path: "/tmp/app.ts" }),
      undefined,
      {
        signal: new AbortController().signal,
      },
    );

    expect(result).toEqual({
      continue: true,
      hookSpecificOutput: {
        hookEventName: "PostToolUse",
        additionalContext: expect.stringContaining(
          "posthog.capture('x'); // [PostHog] Event: \"x\"",
        ),
      },
    });
    const context = (
      result as {
        hookSpecificOutput: { additionalContext: string };
      }
    ).hookSpecificOutput.additionalContext;
    expect(context).toContain("/tmp/app.ts");
  });

  test("writes enriched content to cache keyed by tool_use_id", async () => {
    enrichFileMock.mockReset();
    enrichFileMock.mockResolvedValueOnce(
      "posthog.capture('x'); // [PostHog] Event: \"x\"",
    );

    const cache: EnrichedReadCache = new Map();
    const hook = createReadEnrichmentHook(stubDeps, cache);
    await hook(buildReadHookInput({ file_path: "/tmp/app.ts" }), undefined, {
      signal: new AbortController().signal,
    });

    expect(cache.get("toolu_1")).toContain('// [PostHog] Event: "x"');
  });

  test("does not write to cache when tool_use_id is missing", async () => {
    enrichFileMock.mockReset();
    enrichFileMock.mockResolvedValueOnce("enriched");

    const cache: EnrichedReadCache = new Map();
    const hook = createReadEnrichmentHook(stubDeps, cache);
    await hook(
      buildReadHookInput({ file_path: "/tmp/app.ts", tool_use_id: undefined }),
      undefined,
      { signal: new AbortController().signal },
    );

    expect(cache.size).toBe(0);
  });

  test("handles {type:'text', file:{content}} Read tool_response shape", async () => {
    enrichFileMock.mockReset();
    enrichFileMock.mockResolvedValueOnce("enriched");

    const cache: EnrichedReadCache = new Map();
    const hook = createReadEnrichmentHook(stubDeps, cache);
    await hook(
      buildReadHookInput({
        file_path: "/tmp/app.ts",
        tool_response: {
          type: "text",
          file: {
            filePath: "/tmp/app.ts",
            content: "posthog.capture('x');\n",
            numLines: 1,
            startLine: 1,
            totalLines: 1,
          },
        },
      }),
      undefined,
      { signal: new AbortController().signal },
    );

    const [, , content] = enrichFileMock.mock.calls[0];
    expect(content).toBe("posthog.capture('x');\n");
  });

  test("handles wrapped [{type:'text', text:'...'}] tool_response shape", async () => {
    enrichFileMock.mockReset();
    enrichFileMock.mockResolvedValueOnce("enriched");

    const cache: EnrichedReadCache = new Map();
    const hook = createReadEnrichmentHook(stubDeps, cache);
    await hook(
      buildReadHookInput({
        tool_response: [{ type: "text", text: "     1\tfoo" }],
      }),
      undefined,
      { signal: new AbortController().signal },
    );

    const [, , content] = enrichFileMock.mock.calls[0];
    expect(content).toBe("foo");
  });
});

function buildPreToolUseHookInput(
  toolName: string,
  toolInput: Record<string, unknown>,
): HookInput {
  return {
    session_id: "test-session",
    transcript_path: "/tmp/transcript",
    cwd: "/tmp",
    hook_event_name: "PreToolUse",
    tool_name: toolName,
    tool_use_id: "toolu_1",
    tool_input: toolInput,
  } as HookInput;
}

function buildSettingsManagerStub(
  result: PermissionCheckResult,
): SettingsManager {
  return {
    checkPermission: () => result,
  } as unknown as SettingsManager;
}

describe("createPreToolUseHook", () => {
  const logger = new Logger({ debug: false });
  const posthogExecPermissionRegex =
    /(^|-)(partial-update|update|patch|delete|destroy)(-|$)/i;

  test("defers destructive PostHog exec sub-tool to canUseTool via ask", async () => {
    const settingsManager = buildSettingsManagerStub({
      decision: "allow",
      rule: "mcp__posthog__exec",
      source: "allow",
    });
    const hook = createPreToolUseHook(
      settingsManager,
      logger,
      posthogExecPermissionRegex,
    );
    const result = await hook(
      buildPreToolUseHookInput("mcp__posthog__exec", {
        command: 'call dashboard-update {"id": 1, "name": "x"}',
      }),
      undefined,
      { signal: new AbortController().signal },
    );

    expect(result).toMatchObject({
      continue: true,
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "ask",
      },
    });
  });

  test("allows non-destructive PostHog exec sub-tool via settings rule", async () => {
    const settingsManager = buildSettingsManagerStub({
      decision: "allow",
      rule: "mcp__posthog__exec",
      source: "allow",
    });
    const hook = createPreToolUseHook(
      settingsManager,
      logger,
      posthogExecPermissionRegex,
    );
    const result = await hook(
      buildPreToolUseHookInput("mcp__posthog__exec", {
        command: 'call experiment-get {"id": 1}',
      }),
      undefined,
      { signal: new AbortController().signal },
    );

    expect(result).toEqual({
      continue: true,
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "allow",
        permissionDecisionReason:
          "Allowed by settings rule: mcp__posthog__exec",
      },
    });
  });

  test("allows non-PostHog tool via settings rule unchanged", async () => {
    const settingsManager = buildSettingsManagerStub({
      decision: "allow",
      rule: "Bash(ls:*)",
      source: "allow",
    });
    const hook = createPreToolUseHook(
      settingsManager,
      logger,
      posthogExecPermissionRegex,
    );
    const result = await hook(
      buildPreToolUseHookInput("Bash", { command: "ls -la" }),
      undefined,
      { signal: new AbortController().signal },
    );

    expect(result).toMatchObject({
      hookSpecificOutput: { permissionDecision: "allow" },
    });
  });

  test("defers when destructive rule is partial-update", async () => {
    const settingsManager = buildSettingsManagerStub({
      decision: "allow",
      rule: "mcp__posthog__exec",
      source: "allow",
    });
    const hook = createPreToolUseHook(
      settingsManager,
      logger,
      posthogExecPermissionRegex,
    );
    const result = await hook(
      buildPreToolUseHookInput("mcp__posthog__exec", {
        command: 'call cohorts-partial-update {"id": 1}',
      }),
      undefined,
      { signal: new AbortController().signal },
    );

    expect(result).toMatchObject({
      hookSpecificOutput: { permissionDecision: "ask" },
    });
  });
});

describe("createSignedCommitGuardHook", () => {
  const logger = new Logger();

  function bashInput(command: string): HookInput {
    return {
      session_id: "s",
      transcript_path: "/tmp/t",
      cwd: "/tmp",
      hook_event_name: "PreToolUse",
      tool_name: "Bash",
      tool_use_id: "toolu_1",
      tool_input: { command },
    } as HookInput;
  }

  const guard = createSignedCommitGuardHook(logger);
  const opts = { signal: new AbortController().signal };

  test.each([
    "git commit -m x",
    "git push origin main",
    "git add . && git commit -m 'y'",
    "git -C /repo commit",
    "git --no-pager push",
  ])("denies %s", async (command) => {
    const result = await guard(bashInput(command), undefined, opts);
    expect(result).toMatchObject({
      hookSpecificOutput: { permissionDecision: "deny" },
    });
  });

  test.each([
    "git status",
    "git add .",
    "git fetch origin",
    "git log --grep=commit",
    "git stash push",
    "git ls-remote --heads origin x",
  ])("allows %s", async (command) => {
    const result = await guard(bashInput(command), undefined, opts);
    expect(result).toEqual({ continue: true });
  });

  test("ignores non-Bash tools", async () => {
    const result = await guard(
      { ...bashInput("git commit"), tool_name: "Read" } as HookInput,
      undefined,
      opts,
    );
    expect(result).toEqual({ continue: true });
  });

  test("attempts a heal and keeps the standard message when tools are available", async () => {
    const onHeal = vi.fn().mockResolvedValue(true);
    const healingGuard = createSignedCommitGuardHook(logger, onHeal);

    const result = await healingGuard(
      bashInput("git commit -m x"),
      undefined,
      opts,
    );

    expect(onHeal).toHaveBeenCalledTimes(1);
    expect(result).toMatchObject({
      hookSpecificOutput: {
        permissionDecision: "deny",
        permissionDecisionReason: expect.stringContaining("git_signed_commit"),
      },
    });
  });

  test.each([
    ["resolves false", vi.fn().mockResolvedValue(false)],
    ["throws", vi.fn().mockRejectedValue(new Error("reconnect boom"))],
  ])("reassures the model when the heal %s", async (_label, onHeal) => {
    const healingGuard = createSignedCommitGuardHook(logger, onHeal);

    const result = await healingGuard(
      bashInput("git commit -m x"),
      undefined,
      opts,
    );

    expect(result).toMatchObject({
      hookSpecificOutput: {
        permissionDecision: "deny",
        permissionDecisionReason: expect.stringContaining(
          "safe in the working tree",
        ),
      },
    });
  });
});

describe("createTaskHook", () => {
  const baseInput = {
    session_id: "s",
    transcript_path: "/tmp/t",
    cwd: "/tmp",
  };

  test("ignores hook events without a task_id", async () => {
    const state: TaskState = new Map();
    const onChange = vi.fn(async () => {});
    const hook = createTaskHook(state, onChange);
    const result = await hook(
      { ...baseInput, hook_event_name: "PostToolUse" } as HookInput,
      undefined,
      { signal: new AbortController().signal },
    );
    expect(result).toEqual({ continue: true });
    expect(state.size).toBe(0);
    expect(onChange).not.toHaveBeenCalled();
  });

  test("TaskCreated inserts a pending entry and fires onChange", async () => {
    const state: TaskState = new Map();
    const onChange = vi.fn(async () => {});
    const hook = createTaskHook(state, onChange);
    const result = await hook(
      {
        ...baseInput,
        hook_event_name: "TaskCreated",
        task_id: "t1",
        task_subject: "Fix bug",
        task_description: "details",
      } as unknown as HookInput,
      undefined,
      { signal: new AbortController().signal },
    );
    expect(result).toEqual({ continue: true });
    expect(state.get("t1")).toEqual({
      subject: "Fix bug",
      status: "pending",
      description: "details",
    });
    expect(onChange).toHaveBeenCalledOnce();
  });

  test("TaskCreated is idempotent for an existing task_id", async () => {
    const state: TaskState = new Map([
      [
        "t1",
        {
          subject: "Original",
          status: "in_progress" as const,
        },
      ],
    ]);
    const onChange = vi.fn(async () => {});
    const hook = createTaskHook(state, onChange);
    await hook(
      {
        ...baseInput,
        hook_event_name: "TaskCreated",
        task_id: "t1",
        task_subject: "Overwrite attempt",
      } as unknown as HookInput,
      undefined,
      { signal: new AbortController().signal },
    );
    expect(state.get("t1")?.subject).toBe("Original");
    expect(state.get("t1")?.status).toBe("in_progress");
    expect(onChange).not.toHaveBeenCalled();
  });

  test("TaskCreated without task_subject is a no-op", async () => {
    const state: TaskState = new Map();
    const onChange = vi.fn(async () => {});
    const hook = createTaskHook(state, onChange);
    await hook(
      {
        ...baseInput,
        hook_event_name: "TaskCreated",
        task_id: "t1",
      } as unknown as HookInput,
      undefined,
      { signal: new AbortController().signal },
    );
    expect(state.size).toBe(0);
    expect(onChange).not.toHaveBeenCalled();
  });

  test("TaskCompleted flips status and fires onChange", async () => {
    const state: TaskState = new Map([
      ["t1", { subject: "Existing", status: "in_progress" as const }],
    ]);
    const onChange = vi.fn(async () => {});
    const hook = createTaskHook(state, onChange);
    await hook(
      {
        ...baseInput,
        hook_event_name: "TaskCompleted",
        task_id: "t1",
      } as unknown as HookInput,
      undefined,
      { signal: new AbortController().signal },
    );
    expect(state.get("t1")?.status).toBe("completed");
    expect(onChange).toHaveBeenCalledOnce();
  });

  test("TaskCompleted is a no-op for unknown task_id", async () => {
    const state: TaskState = new Map();
    const onChange = vi.fn(async () => {});
    const hook = createTaskHook(state, onChange);
    await hook(
      {
        ...baseInput,
        hook_event_name: "TaskCompleted",
        task_id: "unknown",
      } as unknown as HookInput,
      undefined,
      { signal: new AbortController().signal },
    );
    expect(state.size).toBe(0);
    expect(onChange).not.toHaveBeenCalled();
  });

  test("TaskCompleted is a no-op for already-completed task", async () => {
    const state: TaskState = new Map([
      ["t1", { subject: "Existing", status: "completed" as const }],
    ]);
    const onChange = vi.fn(async () => {});
    const hook = createTaskHook(state, onChange);
    await hook(
      {
        ...baseInput,
        hook_event_name: "TaskCompleted",
        task_id: "t1",
      } as unknown as HookInput,
      undefined,
      { signal: new AbortController().signal },
    );
    expect(onChange).not.toHaveBeenCalled();
  });

  test("works without an onChange callback", async () => {
    const state: TaskState = new Map();
    const hook = createTaskHook(state);
    await hook(
      {
        ...baseInput,
        hook_event_name: "TaskCreated",
        task_id: "t1",
        task_subject: "Fix bug",
      } as unknown as HookInput,
      undefined,
      { signal: new AbortController().signal },
    );
    expect(state.get("t1")?.subject).toBe("Fix bug");
  });
});
