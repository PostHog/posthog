import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { HookInput, Options } from "@anthropic-ai/claude-agent-sdk";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Logger } from "../../../utils/logger";
import { SUBAGENT_REWRITES } from "../hooks";
import {
  buildSessionOptions,
  buildSystemPrompt,
  toEffortFlagSettings,
  toSdkEffort,
} from "./options";
import { SettingsManager } from "./settings";

const GIT_COMMIT_HOOK_INPUT = {
  session_id: "s",
  transcript_path: "/tmp/t",
  cwd: "/tmp",
  hook_event_name: "PreToolUse",
  tool_name: "Bash",
  tool_use_id: "toolu_1",
  tool_input: { command: "git commit -m x" },
} as HookInput;

async function runPreToolUseHooks(options: Options): Promise<void> {
  const opts = { signal: new AbortController().signal };
  const hooks = (options.hooks?.PreToolUse ?? []).flatMap(
    (entry) => entry.hooks ?? [],
  );
  for (const hook of hooks) {
    await hook(GIT_COMMIT_HOOK_INPUT, undefined, opts);
  }
}

function makeParams() {
  const cwd = path.join(os.tmpdir(), `options-test-${Date.now()}`);
  return {
    cwd,
    mcpServers: {},
    permissionMode: "default" as const,
    canUseTool: async () => ({ behavior: "allow" as const, updatedInput: {} }),
    logger: new Logger(),
    sessionId: "test-session",
    isResume: false,
    settingsManager: new SettingsManager(cwd),
    taskState: new Map(),
  };
}

describe("buildSessionOptions", () => {
  it("replaces unprocessable Read images before model delivery", async () => {
    const options = buildSessionOptions(makeParams());
    const hooks = (options.hooks?.PostToolUse ?? []).flatMap(
      (entry) => entry.hooks ?? [],
    );
    const input = {
      session_id: "s",
      transcript_path: "/tmp/t",
      cwd: "/tmp",
      hook_event_name: "PostToolUse",
      tool_name: "Read",
      tool_use_id: "toolu_image",
      tool_input: { file_path: "/tmp/image.heic" },
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
    } as HookInput;

    const results = await Promise.all(
      hooks.map((hook) =>
        hook(input, undefined, {
          signal: new AbortController().signal,
        }),
      ),
    );

    expect(results).toContainEqual({
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

  it.each(Object.entries(SUBAGENT_REWRITES))(
    'registers rewrite target "%s" → "%s" in options.agents',
    (_source, target) => {
      const options = buildSessionOptions(makeParams());
      const registered = new Set(Object.keys(options.agents ?? {}));

      expect(
        registered.has(target),
        `Rewrite target "${target}" is not registered in options.agents — either register the agent in buildAgents or remove the rewrite.`,
      ).toBe(true);
    },
  );

  it("maps the custom auto mode to the SDK's default mode", () => {
    const options = buildSessionOptions({
      ...makeParams(),
      permissionMode: "auto",
    });
    expect(options.permissionMode).toBe("default");
  });

  it.each(["default", "acceptEdits", "plan", "bypassPermissions"] as const)(
    "passes native SDK mode %s through to options.permissionMode",
    (mode) => {
      const options = buildSessionOptions({
        ...makeParams(),
        permissionMode: mode,
      });
      expect(options.permissionMode).toBe(mode);
    },
  );

  it("preserves caller-provided agents alongside defaults", () => {
    const params = makeParams();
    const options = buildSessionOptions({
      ...params,
      userProvidedOptions: {
        agents: {
          "custom-agent": {
            description: "Custom",
            prompt: "Custom prompt",
          },
        },
      },
    });

    expect(options.agents?.["custom-agent"]).toBeDefined();
    expect(options.agents?.["ph-explore"]).toBeDefined();
  });

  it("lets caller-provided agents override defaults by name", () => {
    const params = makeParams();
    const override = {
      description: "Overridden",
      prompt: "Overridden prompt",
    };
    const options = buildSessionOptions({
      ...params,
      userProvidedOptions: {
        agents: {
          "ph-explore": override,
        },
      },
    });

    expect(options.agents?.["ph-explore"]).toEqual(override);
  });

  it.each([
    ["a new session", () => makeParams()],
    ["a resumed session", () => ({ ...makeParams(), isResume: true })],
  ])(
    "defaults fallbackModel on %s so refusals and overloads retry on another model",
    (_label, params) => {
      const options = buildSessionOptions(params());

      expect(options.fallbackModel).toBe("claude-opus-4-8");
      // The SDK throws at spawn when fallbackModel equals Options.model.
      expect(options.fallbackModel).not.toBe(options.model);
    },
  );

  it("preserves a caller-provided fallbackModel", () => {
    const options = buildSessionOptions({
      ...makeParams(),
      userProvidedOptions: { fallbackModel: "claude-sonnet-5" },
    });

    expect(options.fallbackModel).toBe("claude-sonnet-5");
  });

  it("threads onEnsureLocalToolsConnected into the signed-commit guard (cloud)", async () => {
    const healSpy = vi.fn().mockResolvedValue(true);
    await runPreToolUseHooks(
      buildSessionOptions({
        ...makeParams(),
        cloudMode: true,
        onEnsureLocalToolsConnected: healSpy,
      }),
    );

    expect(healSpy).toHaveBeenCalledTimes(1);
  });

  it("omits the signed-commit guard outside cloud mode", async () => {
    const healSpy = vi.fn().mockResolvedValue(true);
    await runPreToolUseHooks(
      buildSessionOptions({
        ...makeParams(),
        cloudMode: false,
        onEnsureLocalToolsConnected: healSpy,
      }),
    );

    expect(healSpy).not.toHaveBeenCalled();
  });

  describe("rtk and signed-commit guard ordering", () => {
    const originalRtk = process.env.POSTHOG_RTK;
    let dir: string;
    let binary: string;

    beforeEach(() => {
      dir = fs.mkdtempSync(path.join(os.tmpdir(), "rtk-order-"));
      binary = path.join(dir, "rtk");
      fs.writeFileSync(binary, "#!/bin/sh\n");
      process.env.POSTHOG_RTK = binary;
    });

    afterEach(() => {
      if (originalRtk === undefined) {
        delete process.env.POSTHOG_RTK;
      } else {
        process.env.POSTHOG_RTK = originalRtk;
      }
      fs.rmSync(dir, { recursive: true, force: true });
    });

    const bashInput = (command: string): HookInput =>
      ({
        ...(GIT_COMMIT_HOOK_INPUT as object),
        tool_input: { command },
      }) as HookInput;

    type PreToolUseOutput = {
      hookSpecificOutput?: {
        permissionDecision?: string;
        updatedInput?: { command?: string };
      };
    };

    it("registers the signed-commit guard before the rtk rewrite so the guard evaluates raw commands (cloud)", async () => {
      const options = buildSessionOptions({
        ...makeParams(),
        cloudMode: true,
      });
      const hooks = (options.hooks?.PreToolUse ?? []).flatMap(
        (entry) => entry.hooks ?? [],
      );
      const opts = { signal: new AbortController().signal };

      // Identify each hook behaviorally: the guard denies `git commit`, the
      // rtk hook rewrites `git status`. Their registration order is the
      // defense-in-depth guarantee that the guard always sees the raw command.
      let guardIndex = -1;
      let rtkIndex = -1;
      for (const [index, hook] of hooks.entries()) {
        const denyResult = (await hook(
          bashInput("git commit -m x"),
          undefined,
          opts,
        )) as PreToolUseOutput;
        if (
          guardIndex === -1 &&
          denyResult.hookSpecificOutput?.permissionDecision === "deny"
        ) {
          guardIndex = index;
        }

        const rewriteResult = (await hook(
          bashInput("git status"),
          undefined,
          opts,
        )) as PreToolUseOutput;
        if (
          rtkIndex === -1 &&
          rewriteResult.hookSpecificOutput?.updatedInput?.command ===
            `${binary} git status`
        ) {
          rtkIndex = index;
        }
      }

      expect(guardIndex).toBeGreaterThanOrEqual(0);
      expect(rtkIndex).toBeGreaterThanOrEqual(0);
      expect(guardIndex).toBeLessThan(rtkIndex);
    });
  });

  describe("CLAUDE_CODE_EXECUTABLE", () => {
    const originalClaudeExecutable = process.env.CLAUDE_CODE_EXECUTABLE;

    beforeEach(() => {
      delete process.env.CLAUDE_CODE_EXECUTABLE;
    });

    afterEach(() => {
      if (originalClaudeExecutable === undefined) {
        delete process.env.CLAUDE_CODE_EXECUTABLE;
      } else {
        process.env.CLAUDE_CODE_EXECUTABLE = originalClaudeExecutable;
      }
    });

    it.each([
      {
        executablePath: "/tmp/claude",
        expectedPath: "/tmp/claude",
        expectedExecutable: undefined,
        name: "does not force node when Claude executable is a native binary",
      },
      {
        executablePath: "/tmp/cli.js",
        expectedPath: "/tmp/cli.js",
        expectedExecutable: "node",
        name: "uses node when Claude executable is the legacy JavaScript CLI",
      },
      {
        executablePath: undefined,
        expectedPath: undefined,
        expectedExecutable: undefined,
        name: "leaves executable and path unset when CLAUDE_CODE_EXECUTABLE is missing",
      },
      {
        executablePath: "",
        expectedPath: undefined,
        expectedExecutable: undefined,
        name: "leaves executable and path unset when CLAUDE_CODE_EXECUTABLE is empty",
      },
    ])("$name", ({ executablePath, expectedPath, expectedExecutable }) => {
      if (executablePath !== undefined) {
        process.env.CLAUDE_CODE_EXECUTABLE = executablePath;
      }

      const options = buildSessionOptions(makeParams());

      expect(options.pathToClaudeCodeExecutable).toBe(expectedPath);
      expect(options.executable).toBe(expectedExecutable);
    });
  });

  describe("ANTHROPIC_CUSTOM_HEADERS", () => {
    const originalProjectId = process.env.POSTHOG_PROJECT_ID;
    const originalCustomHeaders = process.env.ANTHROPIC_CUSTOM_HEADERS;

    beforeEach(() => {
      delete process.env.POSTHOG_PROJECT_ID;
      delete process.env.ANTHROPIC_CUSTOM_HEADERS;
    });

    afterEach(() => {
      for (const [key, value] of [
        ["POSTHOG_PROJECT_ID", originalProjectId],
        ["ANTHROPIC_CUSTOM_HEADERS", originalCustomHeaders],
      ] as const) {
        if (value === undefined) {
          delete process.env[key];
        } else {
          process.env[key] = value;
        }
      }
    });

    it.each([
      {
        name: "omits the project-scope header when POSTHOG_PROJECT_ID is unset",
        projectId: undefined,
        existingHeaders: undefined,
        bedrockGatewayVariant: undefined,
        expected: [
          "x-posthog-property-$ai_session_id: test-session",
          "x-posthog-use-bedrock-fallback: true",
        ].join("\n"),
      },
      {
        name: "forwards POSTHOG_PROJECT_ID as the gateway project scope",
        projectId: "42",
        existingHeaders: undefined,
        bedrockGatewayVariant: undefined,
        expected: [
          "X-PostHog-Project-Id: 42",
          "x-posthog-property-$ai_session_id: test-session",
          "x-posthog-use-bedrock-fallback: true",
        ].join("\n"),
      },
      {
        name: "preserves pre-existing custom headers ahead of the project-scope header",
        projectId: "42",
        existingHeaders: "x-posthog-property-task_id: task-abc",
        bedrockGatewayVariant: undefined,
        expected: [
          "x-posthog-property-task_id: task-abc",
          "X-PostHog-Project-Id: 42",
          "x-posthog-property-$ai_session_id: test-session",
          "x-posthog-use-bedrock-fallback: true",
        ].join("\n"),
      },
      {
        name: "serves the session from Bedrock on the test variant, without the unreachable fallback header",
        projectId: undefined,
        existingHeaders: undefined,
        bedrockGatewayVariant: "test" as const,
        expected: [
          "x-posthog-property-$ai_session_id: test-session",
          "x-posthog-provider: bedrock",
          "x-posthog-flag-bedrock-llm-gateway: test",
        ].join("\n"),
      },
      {
        name: "keeps the Bedrock failover and sends no provider header on the control variant",
        projectId: undefined,
        existingHeaders: undefined,
        bedrockGatewayVariant: "control" as const,
        expected: [
          "x-posthog-property-$ai_session_id: test-session",
          "x-posthog-use-bedrock-fallback: true",
          "x-posthog-flag-bedrock-llm-gateway: control",
        ].join("\n"),
      },
    ])(
      "$name",
      ({ projectId, existingHeaders, bedrockGatewayVariant, expected }) => {
        if (projectId !== undefined) {
          process.env.POSTHOG_PROJECT_ID = projectId;
        }
        if (existingHeaders !== undefined) {
          process.env.ANTHROPIC_CUSTOM_HEADERS = existingHeaders;
        }

        const headers = buildSessionOptions({
          ...makeParams(),
          bedrockGatewayVariant,
        }).env?.ANTHROPIC_CUSTOM_HEADERS;

        expect(headers).toBe(expected);
      },
    );
  });

  describe("per-session context wiki env", () => {
    const KEYS = [
      "POSTHOG_CONTEXT_LAYER_PATH",
      "POSTHOG_CONTEXT_LAYER_COMMITS_PATH",
      "POSTHOG_PERSONAL_API_KEY",
    ] as const;
    const original: Partial<Record<string, string | undefined>> = {};

    beforeEach(() => {
      for (const key of KEYS) {
        original[key] = process.env[key];
        delete process.env[key];
      }
    });

    afterEach(() => {
      for (const key of KEYS) {
        const value = original[key];
        if (value === undefined) {
          delete process.env[key];
        } else {
          process.env[key] = value;
        }
      }
    });

    // Adapters snapshot process.env at spawn time, so two sessions prepared
    // close together must each see their own mount — and a session without a
    // publish token (impersonation) must not inherit another session's.
    it("gives concurrent sessions their own mounts, ignoring conflicting process.env", () => {
      process.env.POSTHOG_CONTEXT_LAYER_PATH = "/stale/wiki";
      process.env.POSTHOG_CONTEXT_LAYER_COMMITS_PATH = "/stale/commits";
      process.env.POSTHOG_PERSONAL_API_KEY = "other-sessions-token";

      const first = buildSessionOptions({
        ...makeParams(),
        contextWiki: {
          path: "/wiki/a",
          commitsPath: "/api/organizations/a/context_layer/commits/",
          personalApiKey: "token-a",
        },
      }).env;
      const second = buildSessionOptions({
        ...makeParams(),
        contextWiki: {
          path: "/wiki/b",
          commitsPath: "/api/organizations/b/context_layer/commits/",
        },
      }).env;

      expect(first?.POSTHOG_CONTEXT_LAYER_PATH).toBe("/wiki/a");
      expect(first?.POSTHOG_CONTEXT_LAYER_COMMITS_PATH).toBe(
        "/api/organizations/a/context_layer/commits/",
      );
      expect(first?.POSTHOG_PERSONAL_API_KEY).toBe("token-a");
      expect(second?.POSTHOG_CONTEXT_LAYER_PATH).toBe("/wiki/b");
      expect(second?.POSTHOG_PERSONAL_API_KEY).toBeUndefined();
    });

    // Cloud sandboxes still provision these vars per-sandbox in real env.
    it("inherits process.env when no per-session mount is given", () => {
      process.env.POSTHOG_CONTEXT_LAYER_PATH = "/sandbox/wiki";
      process.env.POSTHOG_PERSONAL_API_KEY = "sandbox-token";

      const env = buildSessionOptions(makeParams()).env;

      expect(env?.POSTHOG_CONTEXT_LAYER_PATH).toBe("/sandbox/wiki");
      expect(env?.POSTHOG_PERSONAL_API_KEY).toBe("sandbox-token");
    });
  });

  describe("gateway turn tracing env", () => {
    const KEYS = [
      "CLAUDE_CODE_ENABLE_TELEMETRY",
      "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA",
      "CLAUDE_CODE_PROPAGATE_TRACEPARENT",
      "OTEL_TRACES_EXPORTER",
      "OTEL_EXPORTER_OTLP_PROTOCOL",
      "OTEL_EXPORTER_OTLP_ENDPOINT",
      "TRACEPARENT",
      "TRACESTATE",
    ] as const;
    const original: Partial<Record<string, string | undefined>> = {};

    beforeEach(() => {
      for (const key of KEYS) {
        original[key] = process.env[key];
        delete process.env[key];
      }
    });

    afterEach(() => {
      for (const key of KEYS) {
        const value = original[key];
        if (value === undefined) {
          delete process.env[key];
        } else {
          process.env[key] = value;
        }
      }
    });

    const gatewayEnv = {
      anthropicBaseUrl: "https://gateway.example",
      anthropicAuthToken: "tok",
      openaiBaseUrl: "https://gateway.example/v1",
      openaiApiKey: "tok",
    };

    it("enables per-turn traceparent when routed through the gateway", () => {
      const env = buildSessionOptions({ ...makeParams(), gatewayEnv }).env;

      expect(env?.CLAUDE_CODE_ENABLE_TELEMETRY).toBe("1");
      expect(env?.CLAUDE_CODE_ENHANCED_TELEMETRY_BETA).toBe("1");
      expect(env?.CLAUDE_CODE_PROPAGATE_TRACEPARENT).toBe("1");
      expect(env?.OTEL_TRACES_EXPORTER).toBe("otlp");
      expect(env?.OTEL_EXPORTER_OTLP_PROTOCOL).toBe("http/json");
      expect(env?.OTEL_EXPORTER_OTLP_ENDPOINT).toBe("http://127.0.0.1:9");
    });

    it("honors a caller-supplied OTLP endpoint", () => {
      process.env.OTEL_EXPORTER_OTLP_ENDPOINT =
        "http://collector.internal:4318";

      const env = buildSessionOptions({ ...makeParams(), gatewayEnv }).env;

      expect(env?.OTEL_EXPORTER_OTLP_ENDPOINT).toBe(
        "http://collector.internal:4318",
      );
    });

    it("pins exporter and protocol so an inherited none can't disable tracing", () => {
      process.env.OTEL_TRACES_EXPORTER = "none";
      process.env.OTEL_EXPORTER_OTLP_PROTOCOL = "grpc";

      const env = buildSessionOptions({ ...makeParams(), gatewayEnv }).env;

      expect(env?.OTEL_TRACES_EXPORTER).toBe("otlp");
      expect(env?.OTEL_EXPORTER_OTLP_PROTOCOL).toBe("http/json");
    });

    it("strips inherited TRACEPARENT so turns keep distinct trace ids", () => {
      process.env.TRACEPARENT =
        "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01";
      process.env.TRACESTATE = "vendor=x";

      const env = buildSessionOptions({ ...makeParams(), gatewayEnv }).env;

      expect(env?.TRACEPARENT).toBeUndefined();
      expect(env?.TRACESTATE).toBeUndefined();
    });

    it("leaves BYOK sessions untouched", () => {
      process.env.TRACEPARENT =
        "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01";

      const env = buildSessionOptions(makeParams()).env;

      expect(env?.CLAUDE_CODE_ENABLE_TELEMETRY).toBeUndefined();
      expect(env?.CLAUDE_CODE_PROPAGATE_TRACEPARENT).toBeUndefined();
      expect(env?.TRACEPARENT).toBe(
        "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
      );
    });
  });
});

describe("buildSystemPrompt", () => {
  const promptText = (prompt: Options["systemPrompt"]): string => {
    if (typeof prompt === "string") return prompt;
    if (Array.isArray(prompt)) return prompt.join("\n");
    return prompt?.append ?? "";
  };

  const prompts = [
    { name: "default preset", customPrompt: undefined },
    { name: "string prompt", customPrompt: "You are a test agent." },
    {
      name: "preset with append",
      customPrompt: {
        type: "preset",
        preset: "claude_code",
        append: "Custom append.",
      },
    },
  ];

  it.each(prompts)(
    "appends the narration block with narration on ($name)",
    ({ customPrompt }) => {
      const prompt = buildSystemPrompt(customPrompt, { spokenNarration: true });
      expect(promptText(prompt)).toContain("# Spoken Narration");
    },
  );

  it.each(prompts)(
    "omits the narration block with narration off ($name)",
    ({ customPrompt }) => {
      const prompt = buildSystemPrompt(customPrompt, {
        spokenNarration: false,
      });
      expect(promptText(prompt)).not.toContain("Spoken Narration");
    },
  );

  it.each(prompts)(
    "omits the narration block when opts are absent ($name)",
    ({ customPrompt }) => {
      const prompt = buildSystemPrompt(customPrompt);
      expect(promptText(prompt)).not.toContain("Spoken Narration");
    },
  );

  it("keeps the custom prompt ahead of the appended instructions", () => {
    const prompt = buildSystemPrompt("You are a test agent.", {
      spokenNarration: true,
    });
    expect(typeof prompt).toBe("string");
    expect(prompt).toMatch(/^You are a test agent\./);
  });

  it("keeps the custom append ahead of the appended instructions", () => {
    const prompt = buildSystemPrompt(
      { type: "preset", preset: "claude_code", append: "Custom append." },
      { spokenNarration: true },
    );
    expect(promptText(prompt)).toMatch(/^Custom append\./);
  });

  it.each([
    {
      name: "present via env",
      exists: true,
      viaOption: false,
      expectsBlock: true,
    },
    {
      name: "absent via env",
      exists: false,
      viaOption: false,
      expectsBlock: false,
    },
    {
      name: "present via per-session option",
      exists: true,
      viaOption: true,
      expectsBlock: true,
    },
  ])(
    "gates the context wiki block on the mount directory ($name)",
    ({ exists, viaOption, expectsBlock }) => {
      const prev = process.env.POSTHOG_CONTEXT_LAYER_PATH;
      const mountPath = exists
        ? fs.mkdtempSync(path.join(os.tmpdir(), "context-wiki-"))
        : path.join(os.tmpdir(), "context-wiki-absent-nonexistent");
      if (!viaOption) {
        process.env.POSTHOG_CONTEXT_LAYER_PATH = mountPath;
      }
      try {
        const text = promptText(
          buildSystemPrompt(
            undefined,
            viaOption ? { contextWikiPath: mountPath } : undefined,
          ),
        );
        if (expectsBlock) {
          expect(text).toContain(`mounted at ${mountPath}`);
        } else {
          expect(text).not.toContain("Context Wiki");
        }
      } finally {
        if (exists) {
          fs.rmSync(mountPath, { recursive: true, force: true });
        }
        if (prev === undefined) {
          delete process.env.POSTHOG_CONTEXT_LAYER_PATH;
        } else {
          process.env.POSTHOG_CONTEXT_LAYER_PATH = prev;
        }
      }
    },
  );
});

describe("toSdkEffort", () => {
  it.each([
    ["low", "low"],
    ["medium", "medium"],
    ["high", "high"],
    ["xhigh", "xhigh"],
    ["max", "max"],
    ["ultracode", "xhigh"],
  ] as const)("maps %s to %s", (effort, expected) => {
    expect(toSdkEffort(effort)).toBe(expected);
  });
});

describe("toEffortFlagSettings", () => {
  it.each(["low", "medium", "high", "xhigh", "max"] as const)(
    "passes %s through with the ultracode flag off",
    (effort) => {
      expect(toEffortFlagSettings(effort)).toEqual({
        effortLevel: effort,
        ultracode: false,
      });
    },
  );

  it("maps ultracode to xhigh plus the session flag", () => {
    expect(toEffortFlagSettings("ultracode")).toEqual({
      effortLevel: "xhigh",
      ultracode: true,
    });
  });
});
