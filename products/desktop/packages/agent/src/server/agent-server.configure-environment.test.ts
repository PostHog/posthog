import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { GatewayEnv } from "../adapters/claude/session/options";
import type { Task } from "../types";
import { AgentServer, codexAuthFromGatewayEnv } from "./agent-server";

interface TestableServer {
  configureEnvironment(args?: {
    isInternal?: boolean;
    originProduct?: Task["origin_product"] | null;
    signalReportId?: string | null;
    aiStage?: string | null;
    taskId?: string | null;
    taskRunId?: string | null;
    taskUserId?: number | null;
    taskTitle?: string | null;
    repositories?: string[];
    runtimeAdapter?: string | null;
    sandboxEnvironmentId?: string | null;
    snapshotKind?: string | null;
    prewarmed?: boolean | null;
    executionEnvironment?: "local" | "cloud";
  }): GatewayEnv;
}

const ENV_KEYS_UNDER_TEST = [
  "LLM_GATEWAY_URL",
  "POSTHOG_PROJECT_ID",
  "AI_GATEWAY_URL",
  "AI_GATEWAY_PRODUCTS",
] as const;

describe("AgentServer.configureEnvironment", () => {
  const originalEnv: Partial<Record<string, string | undefined>> = {};

  beforeEach(() => {
    for (const key of ENV_KEYS_UNDER_TEST) {
      originalEnv[key] = process.env[key];
      delete process.env[key];
    }
  });

  afterEach(() => {
    for (const key of ENV_KEYS_UNDER_TEST) {
      const value = originalEnv[key];
      if (value === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = value;
      }
    }
  });

  const buildServer = (mode: "background" | "interactive"): TestableServer =>
    new AgentServer({
      port: 0,
      jwtPublicKey: "test-key",
      apiUrl: "https://us.posthog.com",
      apiKey: "test-api-key",
      projectId: 1,
      mode,
      taskId: "test-task-id",
      runId: "test-run-id",
    }) as unknown as TestableServer;

  it("tags as background_agents when the task is internal", () => {
    const env = buildServer("interactive").configureEnvironment({
      isInternal: true,
    });

    expect(env.anthropicBaseUrl).toBe(
      "https://gateway.us.posthog.com/background_agents",
    );
    expect(env.openaiBaseUrl).toBe(
      "https://gateway.us.posthog.com/background_agents/v1",
    );
  });

  it("tags as posthog_code when the task is not internal", () => {
    const env = buildServer("background").configureEnvironment({
      isInternal: false,
    });

    expect(env.anthropicBaseUrl).toBe(
      "https://gateway.us.posthog.com/posthog_code",
    );
  });

  // The Claude session builder reads posthogProjectId from GatewayEnv to scope
  // the request to a project, so the cloud path must include it.
  it("includes posthogProjectId for the gateway project scope", () => {
    const env = buildServer("background").configureEnvironment({
      isInternal: false,
    });

    expect(env.posthogProjectId).toBe("1");
  });

  // POSTHOG_PROJECT_ID is a server-level constant, safe to keep in process.env.
  it("exports POSTHOG_PROJECT_ID to process.env for tools that inherit it", () => {
    buildServer("background").configureEnvironment({ isInternal: false });

    expect(process.env.POSTHOG_PROJECT_ID).toBe("1");
  });

  it("tags as posthog_code when isInternal is omitted (getTask failure fallback)", () => {
    const env = buildServer("background").configureEnvironment();

    expect(env.anthropicBaseUrl).toBe(
      "https://gateway.us.posthog.com/posthog_code",
    );
  });

  it("ignores mode when picking the gateway product", () => {
    const fromBackground = buildServer("background").configureEnvironment({
      isInternal: false,
    });
    const fromInteractive = buildServer("interactive").configureEnvironment({
      isInternal: false,
    });

    expect(fromBackground.anthropicBaseUrl).toBe(
      fromInteractive.anthropicBaseUrl,
    );
    expect(fromBackground.anthropicBaseUrl).toBe(
      "https://gateway.us.posthog.com/posthog_code",
    );
  });

  it("tags as signals when an internal task has origin_product 'signal_report'", () => {
    const env = buildServer("background").configureEnvironment({
      isInternal: true,
      originProduct: "signal_report",
    });

    expect(env.anthropicBaseUrl).toBe("https://gateway.us.posthog.com/signals");
    expect(env.openaiBaseUrl).toBe("https://gateway.us.posthog.com/signals/v1");
  });

  it("tags as signals when origin_product is 'signal_report' even if the task is not internal", () => {
    const env = buildServer("background").configureEnvironment({
      isInternal: false,
      originProduct: "signal_report",
    });

    expect(env.anthropicBaseUrl).toBe("https://gateway.us.posthog.com/signals");
  });

  it("tags as signals for scout runs (origin_product 'signals_scout'), internal or not", () => {
    const env = buildServer("background").configureEnvironment({
      isInternal: false,
      originProduct: "signals_scout",
    });

    expect(env.anthropicBaseUrl).toBe("https://gateway.us.posthog.com/signals");
  });

  it.each([{ isInternal: true }, { isInternal: false }] as const)(
    "tags as conversations when origin_product is 'support_reply' (isInternal=$isInternal)",
    ({ isInternal }) => {
      const env = buildServer("background").configureEnvironment({
        isInternal,
        originProduct: "support_reply",
      });

      expect(env.anthropicBaseUrl).toBe(
        "https://gateway.us.posthog.com/conversations",
      );
      expect(env.openaiBaseUrl).toBe(
        "https://gateway.us.posthog.com/conversations/v1",
      );
    },
  );

  it.each([{ isInternal: true }, { isInternal: false }] as const)(
    "tags as posthog_code when origin_product is 'loop' (isInternal=$isInternal)",
    ({ isInternal }) => {
      const env = buildServer("background").configureEnvironment({
        isInternal,
        originProduct: "loop",
      });

      expect(env.anthropicBaseUrl).toBe(
        "https://gateway.us.posthog.com/posthog_code",
      );
      expect(env.openaiBaseUrl).toBe(
        "https://gateway.us.posthog.com/posthog_code/v1",
      );
    },
  );

  it("tags as onboarding when a wizard cloud run reaches the gateway", () => {
    const env = buildServer("background").configureEnvironment({
      isInternal: false,
      originProduct: "onboarding",
    });

    expect(env.anthropicBaseUrl).toBe(
      "https://gateway.us.posthog.com/onboarding",
    );
    expect(env.openaiBaseUrl).toBe(
      "https://gateway.us.posthog.com/onboarding/v1",
    );
  });

  // The codex/OpenAI path sets provider http_headers rather than
  // ANTHROPIC_CUSTOM_HEADERS, so the same task metadata must be exposed as a
  // record. It carries both the selected project scope and event attribution.
  it("forwards task metadata and project scope as openaiCustomHeaders", () => {
    const env = buildServer("background").configureEnvironment({
      isInternal: true,
      originProduct: "signal_report",
      signalReportId: "report-123",
      aiStage: "research",
      taskId: "task-abc",
      taskRunId: "run-xyz",
      taskUserId: 42,
      taskTitle: "Fix the bug",
      repositories: ["posthog/posthog", "posthog/posthog-js"],
      runtimeAdapter: "claude",
      sandboxEnvironmentId: "environment-123",
      snapshotKind: "filesystem",
      prewarmed: false,
    });

    expect(env.openaiCustomHeaders).toEqual({
      "x-posthog-property-task_origin_product": "signal_report",
      "x-posthog-property-task_internal": "true",
      "x-posthog-property-signal_report_id": "report-123",
      "x-posthog-property-ai_stage": "research",
      "x-posthog-property-task_id": "task-abc",
      "x-posthog-property-task_run_id": "run-xyz",
      "x-posthog-property-task_user_id": "42",
      "x-posthog-property-task_title": "Fix the bug",
      "x-posthog-property-task_repositories":
        '["posthog/posthog","posthog/posthog-js"]',
      "x-posthog-property-task_runtime_adapter": "claude",
      "x-posthog-property-task_sandbox_environment_id": "environment-123",
      "x-posthog-property-task_snapshot_kind": "filesystem",
      "x-posthog-property-task_prewarmed": "false",
      "x-posthog-property-task_execution_environment": "cloud",
      "x-posthog-property-team_id": "1",
      "x-posthog-property-$ai_session_id": "task-abc",
      "X-PostHog-Project-Id": "1",
    });
  });

  it("forwards task metadata as anthropicCustomHeaders", () => {
    const env = buildServer("background").configureEnvironment({
      isInternal: true,
      originProduct: "signal_report",
      signalReportId: "report-123",
      aiStage: "research",
      taskId: "task-abc",
      taskRunId: "run-xyz",
      taskUserId: 42,
      taskTitle: "Fix the bug",
      repositories: ["posthog/posthog", "posthog/posthog-js"],
      runtimeAdapter: "claude",
      sandboxEnvironmentId: "environment-123",
      snapshotKind: "filesystem",
      prewarmed: false,
    });

    expect(env.anthropicCustomHeaders).toBe(
      [
        "x-posthog-property-task_origin_product: signal_report",
        "x-posthog-property-task_internal: true",
        "x-posthog-property-signal_report_id: report-123",
        "x-posthog-property-ai_stage: research",
        "x-posthog-property-task_id: task-abc",
        "x-posthog-property-task_run_id: run-xyz",
        "x-posthog-property-task_user_id: 42",
        "x-posthog-property-task_title: Fix the bug",
        'x-posthog-property-task_repositories: ["posthog/posthog","posthog/posthog-js"]',
        "x-posthog-property-task_runtime_adapter: claude",
        "x-posthog-property-task_sandbox_environment_id: environment-123",
        "x-posthog-property-task_snapshot_kind: filesystem",
        "x-posthog-property-task_prewarmed: false",
        "x-posthog-property-task_execution_environment: cloud",
        "X-PostHog-Project-Id: 1",
      ].join("\n"),
    );
  });

  it("omits ai_stage from anthropicCustomHeaders when not provided", () => {
    const env = buildServer("background").configureEnvironment({
      isInternal: false,
      taskId: "task-abc",
    });

    expect(env.anthropicCustomHeaders).not.toContain("ai_stage");
  });

  // A signals_scout title is multi-line; it must not inject extra header lines.
  it("collapses newlines in the task title", () => {
    const env = buildServer("background").configureEnvironment({
      isInternal: false,
      taskId: "task-abc",
      taskTitle: "[sandbox_prompt:signals_scout:signals-scout-logs]\nLine two",
    });

    expect(env.anthropicCustomHeaders).toContain(
      "x-posthog-property-task_title: [sandbox_prompt:signals_scout:signals-scout-logs] Line two",
    );
  });

  it("omits signal_report_id from anthropicCustomHeaders for non-report tasks", () => {
    const env = buildServer("background").configureEnvironment({
      isInternal: false,
      taskId: "task-abc",
    });

    expect(env.anthropicCustomHeaders).not.toContain("signal_report_id");
  });

  it("omits optional task metadata from anthropicCustomHeaders when not provided", () => {
    const env = buildServer("background").configureEnvironment({
      isInternal: false,
    });

    expect(env.anthropicCustomHeaders).toBe(
      "x-posthog-property-task_internal: false\n" +
        "x-posthog-property-task_execution_environment: cloud\n" +
        "X-PostHog-Project-Id: 1",
    );
  });

  it("tags as slack_app when the task was initiated from Slack", () => {
    const env = buildServer("interactive").configureEnvironment({
      originProduct: "slack",
    });

    expect(env.anthropicBaseUrl).toBe(
      "https://gateway.us.posthog.com/slack_app",
    );
    expect(env.openaiBaseUrl).toBe(
      "https://gateway.us.posthog.com/slack_app/v1",
    );
  });

  it("prefers slack_app over background_agents when both signals are present", () => {
    const env = buildServer("interactive").configureEnvironment({
      isInternal: true,
      originProduct: "slack",
    });

    expect(env.anthropicBaseUrl).toBe(
      "https://gateway.us.posthog.com/slack_app",
    );
  });

  it("falls back to posthog_code for non-slack origin products", () => {
    const env = buildServer("background").configureEnvironment({
      originProduct: "user_created",
    });

    expect(env.anthropicBaseUrl).toBe(
      "https://gateway.us.posthog.com/posthog_code",
    );
  });

  it("routes PostHog AI origin through the posthog_ai product", () => {
    const env = buildServer("interactive").configureEnvironment({
      originProduct: "posthog_ai",
    });

    expect(env.anthropicBaseUrl).toBe(
      "https://gateway.us.posthog.com/posthog_ai",
    );
    expect(env.openaiBaseUrl).toBe(
      "https://gateway.us.posthog.com/posthog_ai/v1",
    );
  });

  it("folds the task id into the codex session header only", () => {
    const env = buildServer("interactive").configureEnvironment({
      taskId: "task-123",
    });

    expect(env.openaiCustomHeaders?.["x-posthog-property-$ai_session_id"]).toBe(
      "task-123",
    );
    expect(env.anthropicCustomHeaders ?? "").not.toContain("$ai_session_id");
  });

  it("omits the codex session header without a task id", () => {
    const env = buildServer("interactive").configureEnvironment({});

    expect(
      env.openaiCustomHeaders?.["x-posthog-property-$ai_session_id"],
    ).toBeUndefined();
  });

  it("appends the resolved product to a LLM_GATEWAY_URL override base", () => {
    // The override is treated as a base URL. The product slug is always
    // appended so the gateway routes to the correct product config — a bare
    // host like http://ngrok.test/proxy would otherwise hit the catch-all
    // llm_gateway product, which OAuth tokens cannot use.
    process.env.LLM_GATEWAY_URL = "http://ngrok.test/proxy";

    const env = buildServer("background").configureEnvironment({
      isInternal: true,
    });

    expect(env.anthropicBaseUrl).toBe(
      "http://ngrok.test/proxy/background_agents",
    );
    expect(env.openaiBaseUrl).toBe(
      "http://ngrok.test/proxy/background_agents/v1",
    );
  });
});

describe("AgentServer.configureEnvironment on the Go ai-gateway", () => {
  const originalEnv: Partial<Record<string, string | undefined>> = {};
  const ENV_KEYS = [
    "LLM_GATEWAY_URL",
    "POSTHOG_PROJECT_ID",
    "AI_GATEWAY_URL",
    "AI_GATEWAY_PRODUCTS",
    "AI_GATEWAY_TOKEN",
  ];
  const GO_GATEWAY = "https://ai-gateway.us.posthog.com";
  const SCOPED_TOKEN = "phe_test_scoped_token";

  beforeEach(() => {
    for (const key of ENV_KEYS) {
      originalEnv[key] = process.env[key];
      delete process.env[key];
    }
    process.env.AI_GATEWAY_URL = GO_GATEWAY;
    process.env.AI_GATEWAY_PRODUCTS = [
      "signals_scout",
      "signals_research",
      "signals_implementation",
      "signals_repo_selection",
      "background_agents",
    ].join(",");
    process.env.AI_GATEWAY_TOKEN = SCOPED_TOKEN;
  });

  afterEach(() => {
    for (const key of ENV_KEYS) {
      const value = originalEnv[key];
      if (value === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = value;
      }
    }
  });

  const buildServer = (): TestableServer =>
    new AgentServer({
      port: 0,
      jwtPublicKey: "test-key",
      apiUrl: "https://us.posthog.com",
      apiKey: "test-api-key",
      projectId: 42,
      mode: "background",
      taskId: "test-task-id",
      runId: "test-run-id",
    }) as unknown as TestableServer;

  const parseBlob = (headerLines: string): Record<string, unknown> => {
    const prefix = "X-PostHog-Properties: ";
    expect(headerLines.startsWith(prefix)).toBe(true);
    return JSON.parse(headerLines.slice(prefix.length));
  };

  it("drops the product slug from the base URLs", () => {
    const env = buildServer().configureEnvironment({
      originProduct: "signals_scout",
      aiStage: "scout",
    });

    expect(env.anthropicBaseUrl).toBe(GO_GATEWAY);
    expect(env.openaiBaseUrl).toBe(`${GO_GATEWAY}/v1`);
  });

  it("honours an explicit AI_GATEWAY_URL with a trailing /v1", () => {
    process.env.AI_GATEWAY_URL = "https://ai-gateway.dev.posthog.dev/v1";
    const env = buildServer().configureEnvironment({
      originProduct: "signal_report",
      aiStage: "research",
    });

    expect(env.anthropicBaseUrl).toBe("https://ai-gateway.dev.posthog.dev");
    expect(env.openaiBaseUrl).toBe("https://ai-gateway.dev.posthog.dev/v1");
  });

  it("leaves an unlisted product on the Python gateway, slug and all", () => {
    process.env.AI_GATEWAY_PRODUCTS = "signals_scout";
    const env = buildServer().configureEnvironment({ isInternal: false });

    expect(env.anthropicBaseUrl).toBe(
      "https://gateway.us.posthog.com/posthog_code",
    );
    expect(env.anthropicCustomHeaders).toContain(
      "x-posthog-property-task_internal",
    );
  });

  it.each([
    ["scout", "signals_scout"],
    ["research", "signals_research"],
    ["implementation", "signals_implementation"],
    ["repo_selection", "signals_repo_selection"],
  ])("sends ai_product %s as %s", (aiStage, expected) => {
    const env = buildServer().configureEnvironment({
      originProduct: "signal_report",
      aiStage,
    });

    expect(parseBlob(env.anthropicCustomHeaders ?? "").ai_product).toBe(
      expected,
    );
  });

  it("carries stage and team attribution in the blob for both adapters", () => {
    const env = buildServer().configureEnvironment({
      originProduct: "signal_report",
      aiStage: "scout",
      taskId: "task-1",
      taskRunId: "run-1",
    });

    const expected = {
      task_origin_product: "signal_report",
      task_internal: false,
      ai_stage: "scout",
      task_id: "task-1",
      task_run_id: "run-1",
      ai_product: "signals_scout",
      team_id: 42,
    };
    expect(parseBlob(env.anthropicCustomHeaders ?? "")).toMatchObject(expected);
    expect(
      JSON.parse(env.openaiCustomHeaders?.["X-PostHog-Properties"] ?? "{}"),
    ).toMatchObject(expected);
  });

  it("emits attribution as one X-PostHog-Properties blob, not per-property headers", () => {
    // Asserts the gateway env this function produces. The Claude adapter's
    // buildEnvironment later appends `X-PostHog-Project-Id` and
    // `x-posthog-use-bedrock-fallback` as separate header lines; the Go gateway
    // reads only the blob (team_id is already in it, and it does Bedrock
    // failover itself), so those extra lines are inert on this path.
    const env = buildServer().configureEnvironment({
      originProduct: "signal_report",
      aiStage: "scout",
    });

    expect(env.anthropicCustomHeaders).not.toContain("x-posthog-property-");
    expect(env.anthropicCustomHeaders?.split("\n")).toHaveLength(1);
    expect(Object.keys(env.openaiCustomHeaders ?? {})).toEqual([
      "X-PostHog-Properties",
    ]);
  });

  it("keeps non-signals products on their existing ai_product name", () => {
    const env = buildServer().configureEnvironment({ isInternal: true });

    expect(parseBlob(env.anthropicCustomHeaders ?? "").ai_product).toBe(
      "background_agents",
    );
  });

  it("authenticates with the scoped token on the Go path", () => {
    const env = buildServer().configureEnvironment({
      originProduct: "signals_scout",
      aiStage: "scout:web-analytics",
    });

    expect(env.anthropicBaseUrl).toBe(GO_GATEWAY);
    expect(env.anthropicAuthToken).toBe(SCOPED_TOKEN);
    expect(env.openaiApiKey).toBe(SCOPED_TOKEN);
  });

  it("falls back to the Python gateway when no scoped token is present", () => {
    delete process.env.AI_GATEWAY_TOKEN;
    const env = buildServer().configureEnvironment({
      originProduct: "signals_scout",
      aiStage: "scout",
    });

    expect(env.anthropicBaseUrl).toBe("https://gateway.us.posthog.com/signals");
    expect(env.anthropicAuthToken).toBe("test-api-key");
    expect(env.openaiApiKey).toBe("test-api-key");
  });

  it("feeds the codex session the gateway bearer, not the raw run credential", () => {
    const routed = buildServer().configureEnvironment({
      originProduct: "signals_scout",
      aiStage: "scout:web-analytics",
    });
    expect(codexAuthFromGatewayEnv(routed)).toEqual({
      apiBaseUrl: `${GO_GATEWAY}/v1`,
      apiKey: SCOPED_TOKEN,
    });

    delete process.env.AI_GATEWAY_TOKEN;
    const unrouted = buildServer().configureEnvironment({ isInternal: false });
    expect(codexAuthFromGatewayEnv(unrouted).apiKey).toBe("test-api-key");
  });

  it("keeps the OAuth token as bearer for unrouted products", () => {
    const env = buildServer().configureEnvironment({ isInternal: false });

    expect(env.anthropicBaseUrl).toBe(
      "https://gateway.us.posthog.com/posthog_code",
    );
    expect(env.anthropicAuthToken).toBe("test-api-key");
    expect(env.openaiApiKey).toBe("test-api-key");
  });
});
