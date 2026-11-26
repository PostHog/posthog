import { type SpanContext, TraceFlags } from "@opentelemetry/api";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { GatewayEnv } from "../adapters/claude/session/options";
import { AgentServer } from "./agent-server";
import { codexAuthFromGatewayEnv, type GatewayEnvInput } from "./gateway-env";

interface TestableServer {
  configureEnvironment(args?: GatewayEnvInput): GatewayEnv;
}

const RUN_SPAN_CONTEXT: SpanContext = {
  traceId: "1234567890abcdef1234567890abcdef",
  spanId: "1234567890abcdef",
  traceFlags: TraceFlags.SAMPLED,
};

describe("AgentServer.configureEnvironment on the Go ai-gateway", () => {
  const originalEnv: Partial<Record<string, string | undefined>> = {};
  const ENV_KEYS = [
    "POSTHOG_PROJECT_ID",
    "AI_GATEWAY_URL",
    "AI_GATEWAY_PRODUCTS",
    "AI_GATEWAY_TOKEN",
    "AI_GATEWAY_PRODUCT",
    "AI_GATEWAY_AI_STAGE",
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

  const buildServer = (
    overrides: { serviceTier?: "default" | "priority" | "flex" } = {},
  ): TestableServer =>
    new AgentServer({
      port: 0,
      jwtPublicKey: "test-key",
      apiUrl: "https://us.posthog.com",
      apiKey: "test-api-key",
      projectId: 42,
      mode: "background",
      taskId: "test-task-id",
      runId: "test-run-id",
      ...overrides,
    }) as unknown as TestableServer;

  const parseBlob = (headerLines: string): Record<string, unknown> => {
    const prefix = "X-PostHog-Properties: ";
    expect(headerLines.startsWith(prefix)).toBe(true);
    return JSON.parse(headerLines.slice(prefix.length).split("\n")[0]);
  };

  it("drops the product slug from the base URLs", () => {
    const env = buildServer().configureEnvironment({
      gatewayProduct: "signals",
      aiStage: "scout",
    });

    expect(env.anthropicBaseUrl).toBe(GO_GATEWAY);
    expect(env.openaiBaseUrl).toBe(`${GO_GATEWAY}/v1`);
  });

  it("honours an explicit AI_GATEWAY_URL with a trailing /v1", () => {
    process.env.AI_GATEWAY_URL = "https://ai-gateway.dev.posthog.dev/v1";
    const env = buildServer().configureEnvironment({
      gatewayProduct: "signals",
      aiStage: "research",
    });

    expect(env.anthropicBaseUrl).toBe("https://ai-gateway.dev.posthog.dev");
    expect(env.openaiBaseUrl).toBe("https://ai-gateway.dev.posthog.dev/v1");
  });

  // The Claude session builder reads posthogProjectId from GatewayEnv to scope
  // the request to a project, and tools inherit POSTHOG_PROJECT_ID.
  it("scopes the env and process.env to the server's project", () => {
    const env = buildServer().configureEnvironment({ isInternal: true });

    expect(env.posthogProjectId).toBe("42");
    expect(process.env.POSTHOG_PROJECT_ID).toBe("42");
  });

  it.each([
    {
      route: "an unlisted product",
      env: { AI_GATEWAY_PRODUCTS: "signals_scout" },
      input: { isInternal: false },
      message: "AI_GATEWAY_PRODUCTS",
    },
    {
      route: "a routed product without a scoped token",
      env: { AI_GATEWAY_TOKEN: "" },
      input: { gatewayProduct: "signals", aiStage: "scout" },
      message: "AI_GATEWAY_TOKEN is required for ai_product signals_scout",
    },
  ] as const)("refuses $route", ({ env, input, message }) => {
    Object.assign(process.env, env);

    expect(() => buildServer().configureEnvironment(input)).toThrow(message);
  });

  it.each([
    ["scout", "signals_scout"],
    ["research", "signals_research"],
    ["implementation", "signals_implementation"],
    ["repo_selection", "signals_repo_selection"],
  ])("sends ai_product %s as %s", (aiStage, expected) => {
    const env = buildServer().configureEnvironment({
      gatewayProduct: "signals",
      aiStage,
    });

    expect(parseBlob(env.anthropicCustomHeaders ?? "").ai_product).toBe(
      expected,
    );
  });

  it("carries stage and team attribution in the blob for both adapters", () => {
    const env = buildServer().configureEnvironment({
      runSpanContext: RUN_SPAN_CONTEXT,
      originProduct: "signal_report",
      gatewayProduct: "signals",
      aiStage: "scout",
      taskId: "task-1",
      taskRunId: "run-1",
    });

    const expected = {
      task_run_trace_id: RUN_SPAN_CONTEXT.traceId,
      task_run_span_id: RUN_SPAN_CONTEXT.spanId,
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
    expect(env.anthropicCustomHeaders).toContain(
      "X-PostHog-Task-Run-Id: run-1",
    );
    expect(env.openaiCustomHeaders).toMatchObject({
      "X-PostHog-Task-Run-Id": "run-1",
    });
  });

  it("emits attribution as one X-PostHog-Properties blob, not per-property headers", () => {
    // Asserts the gateway env this function produces. The Claude adapter's
    // buildEnvironment later appends `X-PostHog-Project-Id` and
    // `x-posthog-use-bedrock-fallback` as separate header lines; the Go gateway
    // reads only the blob (team_id is already in it, and it does Bedrock
    // failover itself), so those extra lines are inert on this path.
    const env = buildServer().configureEnvironment({
      gatewayProduct: "signals",
      aiStage: "scout",
    });

    expect(env.anthropicCustomHeaders).not.toContain("x-posthog-property-");
    expect(env.anthropicCustomHeaders?.split("\n")).toHaveLength(1);
    expect(Object.keys(env.openaiCustomHeaders ?? {})).toEqual([
      "X-PostHog-Properties",
    ]);
    const properties = parseBlob(env.anthropicCustomHeaders ?? "");
    expect(properties).not.toHaveProperty("task_run_trace_id");
    expect(properties).not.toHaveProperty("task_run_span_id");
    expect(properties).not.toHaveProperty("ai_agent_name");
    expect(properties).not.toHaveProperty("signal_report_id");
  });

  it("sends the task id as the Go gateway session header", () => {
    const env = buildServer().configureEnvironment({
      gatewayProduct: "signals",
      aiStage: "scout",
      taskId: "task-1",
    });

    expect(env.anthropicCustomHeaders).toContain(
      "X-PostHog-Session-Id: task-1",
    );
    expect(env.openaiCustomHeaders).toMatchObject({
      "X-PostHog-Session-Id": "task-1",
    });
    expect(parseBlob(env.anthropicCustomHeaders ?? "")).not.toHaveProperty(
      "$ai_session_id",
    );
  });

  // The gateway writes the tier into the OpenAI body from this header, so a
  // run that loses it silently runs on the standard queue and a flex trial
  // measures nothing. Codex-only: the Claude header lines never carry it.
  it.each([
    { serviceTier: "flex", fallback: "standard" },
    { serviceTier: "default", fallback: undefined },
    { serviceTier: "priority", fallback: undefined },
    { serviceTier: undefined, fallback: undefined },
  ] as const)(
    "sends service tier $serviceTier with fallback $fallback on the OpenAI record",
    ({ serviceTier, fallback }) => {
      const env = buildServer({ serviceTier }).configureEnvironment({
        gatewayProduct: "signals",
        aiStage: "scout",
      });

      expect(env.openaiCustomHeaders?.["X-PostHog-Service-Tier"]).toBe(
        serviceTier,
      );
      expect(env.openaiCustomHeaders?.["X-PostHog-Flex-Fallback"]).toBe(
        fallback,
      );
      expect(env.anthropicCustomHeaders).not.toContain(
        "X-PostHog-Service-Tier",
      );
      expect(env.anthropicCustomHeaders).not.toContain(
        "X-PostHog-Flex-Fallback",
      );
    },
  );

  // The header outranks `traceparent`, so giving it to Claude would replace the
  // per-turn ids its CLI mints with one id for the whole run.
  it("names the run as X-PostHog-Trace-Id for codex only", () => {
    const codex = buildServer().configureEnvironment({
      gatewayProduct: "signals",
      aiStage: "scout",
      taskRunId: "run-1",
      runtimeAdapter: "codex",
    });
    const claude = buildServer().configureEnvironment({
      gatewayProduct: "signals",
      aiStage: "scout",
      taskRunId: "run-1",
      runtimeAdapter: "claude",
    });

    expect(codex.openaiCustomHeaders?.["X-PostHog-Trace-Id"]).toBe("run-1");
    expect(codex.anthropicCustomHeaders).not.toContain("X-PostHog-Trace-Id");
    expect(claude.openaiCustomHeaders?.["X-PostHog-Trace-Id"]).toBeUndefined();
  });

  // Codex sub-agents reach the gateway with the process headers only, so the
  // shared cache scope has to ride the OpenAI record, and only when the run asks.
  it("sends the shared prompt cache scope only when the run asks for it", () => {
    const run: GatewayEnvInput = {
      gatewayProduct: "signals",
      aiStage: "scout",
      runtimeAdapter: "codex",
    };
    const shared = buildServer().configureEnvironment({
      ...run,
      sharedPromptCache: true,
    });
    const keyed = buildServer().configureEnvironment(run);

    expect(shared.openaiCustomHeaders?.["X-PostHog-Prompt-Cache-Scope"]).toBe(
      "shared",
    );
    expect(shared.anthropicCustomHeaders).not.toContain(
      "X-PostHog-Prompt-Cache-Scope",
    );
    expect(
      keyed.openaiCustomHeaders?.["X-PostHog-Prompt-Cache-Scope"],
    ).toBeUndefined();
  });

  it("keeps non-signals products on their existing ai_product name", () => {
    const env = buildServer().configureEnvironment({ isInternal: true });

    expect(parseBlob(env.anthropicCustomHeaders ?? "").ai_product).toBe(
      "background_agents",
    );
  });

  // A failed boot fetch leaves aiStage null; without the env values the minted token goes unused.
  it("routes on the worker's product and stage when the run fetch yielded no stage", () => {
    process.env.AI_GATEWAY_PRODUCT = "signals_scout";
    process.env.AI_GATEWAY_AI_STAGE = "scout:web-analytics";
    const env = buildServer().configureEnvironment({
      gatewayProduct: "signals",
      aiStage: null,
      taskId: "task-1",
      taskRunId: "run-1",
    });

    expect(env.anthropicBaseUrl).toBe(GO_GATEWAY);
    expect(env.anthropicAuthToken).toBe(SCOPED_TOKEN);
    expect(parseBlob(env.anthropicCustomHeaders ?? "")).toMatchObject({
      ai_product: "signals_scout",
      ai_stage: "scout:web-analytics",
      task_run_id: "run-1",
    });
  });

  it("feeds the codex session the scoped token, not the raw run credential", () => {
    const routed = buildServer().configureEnvironment({
      gatewayProduct: "signals",
      aiStage: "scout:web-analytics",
    });

    expect(routed.anthropicAuthToken).toBe(SCOPED_TOKEN);
    expect(codexAuthFromGatewayEnv(routed)).toEqual({
      apiBaseUrl: `${GO_GATEWAY}/v1`,
      apiKey: SCOPED_TOKEN,
    });
  });
});
