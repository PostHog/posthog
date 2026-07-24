import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { GatewayEnv } from "../adapters/claude/session/options";
import type { Task } from "../types";
import { AgentServer } from "./agent-server";

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
  }): GatewayEnv;
}

const ENV_KEYS_UNDER_TEST = ["LLM_GATEWAY_URL", "POSTHOG_PROJECT_ID"] as const;

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

  // The Claude session builder reads posthogProjectId from GatewayEnv to emit
  // the `x-posthog-property-team_id` attribution header (see
  // adapters/claude/session/options.ts), so the cloud path must include it.
  it("includes posthogProjectId for the team_id attribution header", () => {
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

  // The codex/OpenAI path sets provider http_headers rather than
  // ANTHROPIC_CUSTOM_HEADERS, so the same task metadata must be exposed as a
  // record — including team_id, which the Claude path adds separately in
  // buildEnvironment.
  it("forwards task metadata (plus team_id) as openaiCustomHeaders", () => {
    const env = buildServer("background").configureEnvironment({
      isInternal: true,
      originProduct: "signal_report",
      signalReportId: "report-123",
      aiStage: "research",
      taskId: "task-abc",
      taskRunId: "run-xyz",
      taskUserId: 42,
      taskTitle: "Fix the bug",
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
      "x-posthog-property-team_id": "1",
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
      "x-posthog-property-task_internal: false",
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
