import { classifyGatewayLimitError } from "@posthog/shared";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthService } from "../auth/auth";
import type { GatewayTokenService } from "./gateway-token";
import type {
  LlmGatewayAuth,
  LlmGatewayEndpoints,
  LlmGatewayHost,
  LlmGatewayLogger,
} from "./identifiers";
import { LlmGatewayError, LlmGatewayService } from "./llm-gateway";
import type { GatewayRoute } from "./schemas";

const API_HOST = "https://app.example.com";

function createJsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const GO_ROUTE: Extract<GatewayRoute, { mode: "go" }> = {
  mode: "go",
  gatewayUrl: "https://ai-gateway.us.posthog.com",
  token: "phe_one",
  expiresAt: Date.now() + 3_600_000,
  capUsd: "200",
  allowedModels: ["claude-haiku-4-5", "claude-default"],
  productModels: ["claude-haiku-4-5", "claude-default"],
  plan: "paid",
  projectId: 42,
  teamId: 7,
  source: "mint",
};

function createService(
  authenticatedFetch: LlmGatewayAuth["authenticatedFetch"],
  options: {
    route?: GatewayRoute;
    remint?: GatewayTokenService["remint"];
    fetch?: LlmGatewayAuth["fetch"];
  } = {},
) {
  const auth: LlmGatewayAuth = {
    getValidAccessToken: vi
      .fn()
      .mockResolvedValue({ accessToken: "tok", apiHost: API_HOST }),
    authenticatedFetch,
    fetch: options.fetch,
  };

  const endpoints: LlmGatewayEndpoints = {
    messagesUrl: (host) => `${host}/gateway/v1/messages`,
    usageUrl: (host, projectId) =>
      `${host}/api/projects/${projectId}/desktop/usage/`,
    legacyUsageUrl: (host) => `${host}/gateway/usage`,
    defaultModel: "claude-default",
  };
  const gatewayTokens = {
    getRoute: vi
      .fn()
      .mockResolvedValue(options.route ?? { mode: "legacy", reason: "test" }),
    remint: options.remint ?? vi.fn().mockResolvedValue(null),
    fallBack: vi.fn(),
    clearBlocked: vi.fn(),
  } as unknown as GatewayTokenService;

  const host: LlmGatewayHost = { ...auth, ...endpoints };

  const log: LlmGatewayLogger = {
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  };
  const logger = { ...log, scope: () => log };

  const orgListeners: Array<(state: { currentOrgId: string | null }) => void> =
    [];
  const authService = {
    getState: () => ({ currentOrgId: "org-1", currentProjectId: 42 }),
    on: (
      _event: string,
      listener: (state: { currentOrgId: string | null }) => void,
    ) => {
      orgListeners.push(listener);
    },
  } as unknown as AuthService;
  const emitAuthState = (currentOrgId: string | null) => {
    for (const listener of orgListeners) {
      listener({ currentOrgId });
    }
  };

  const service = new LlmGatewayService(
    host,
    logger,
    authService,
    gatewayTokens,
  );
  return {
    service,
    auth,
    endpoints,
    log,
    emitAuthState,
    gatewayTokens,
  };
}

const SUCCESS_BODY = {
  id: "msg_1",
  type: "message" as const,
  role: "assistant" as const,
  content: [{ type: "text" as const, text: "hello world" }],
  model: "claude-resolved",
  stop_reason: "end_turn",
  usage: { input_tokens: 12, output_tokens: 7 },
};

const MODEL_GATE_BODY = {
  error: {
    message:
      "Model 'claude-haiku-4-5' needs a paid PostHog plan. Models available on the free tier: @cf/zai-org/glm-5.2. Add a payment method to your organization to unlock all models. (rate_limit)",
    type: "permission_error",
    code: "model_gate",
  },
};

describe("LlmGatewayService.prompt", () => {
  beforeEach(() => {
    vi.useRealTimers();
  });

  it("returns parsed content, model, and usage on success", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(createJsonResponse(SUCCESS_BODY));
    const { service } = createService(fetchMock);

    const result = await service.prompt([{ role: "user", content: "hi" }]);

    expect(result).toEqual({
      content: "hello world",
      model: "claude-resolved",
      stopReason: "end_turn",
      usage: { inputTokens: 12, outputTokens: 7 },
    });
  });

  it("posts to the resolved messages URL with the default model and request body", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(createJsonResponse(SUCCESS_BODY));
    const { service } = createService(fetchMock);

    await service.prompt([{ role: "user", content: "hi" }], {
      system: "be terse",
      maxTokens: 256,
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${API_HOST}/gateway/v1/messages`);
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({ "X-PostHog-Project-Id": "42" });
    const body = JSON.parse(init.body);
    expect(body.model).toBe("claude-default");
    expect(body.system).toBe("be terse");
    expect(body.max_tokens).toBe(256);
    expect(body.stream).toBe(false);
  });

  it("forwards posthogProperties as x-posthog-property-* request headers and skips nulls", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(createJsonResponse(SUCCESS_BODY));
    const { service } = createService(fetchMock);

    await service.prompt([{ role: "user", content: "hi" }], {
      posthogProperties: {
        $ai_span_name: "pr_description",
        task_id: 42,
        is_dry_run: false,
        // Null/undefined values are dropped so the gateway doesn't see
        // literal "null" strings on the captured event.
        unused: null,
        skipped: undefined,
        // Newlines and non-ASCII characters are sanitized so no HTTP client
        // (undici, Bun's fetch) rejects the request before it's sent.
        rich: "line one\nline two — done 🎉",
      },
    });

    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers).toMatchObject({
      "x-posthog-property-$ai_span_name": "pr_description",
      "x-posthog-property-task_id": "42",
      "x-posthog-property-is_dry_run": "false",
      "x-posthog-property-rich": "line one line two  done ",
    });
    expect(init.headers).not.toHaveProperty("x-posthog-property-unused");
    expect(init.headers).not.toHaveProperty("x-posthog-property-skipped");
  });

  it("throws a typed LlmGatewayError with parsed error fields on non-ok response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      createJsonResponse(
        {
          error: {
            message: "rate limited",
            type: "rate_limit",
            code: "slow_down",
          },
        },
        429,
      ),
    );
    const { service } = createService(fetchMock);

    await expect(
      service.prompt([{ role: "user", content: "hi" }]),
    ).rejects.toMatchObject({
      name: "LlmGatewayError",
      message: "rate limited",
      type: "rate_limit",
      code: "slow_down",
      statusCode: 429,
    });
  });

  it("surfaces a FastAPI bare-string detail as the error message", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      createJsonResponse(
        {
          detail: "OAuth application not authorized for product 'posthog_code'",
        },
        403,
      ),
    );
    const { service } = createService(fetchMock);

    await expect(
      service.prompt([{ role: "user", content: "hi" }]),
    ).rejects.toMatchObject({
      name: "LlmGatewayError",
      message: "OAuth application not authorized for product 'posthog_code'",
      type: "unknown_error",
      statusCode: 403,
    });
  });

  it("retries once on the free-tier model when the model gate 403s", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(createJsonResponse(MODEL_GATE_BODY, 403))
      .mockResolvedValueOnce(createJsonResponse(SUCCESS_BODY));
    const { service } = createService(fetchMock);

    const result = await service.prompt([{ role: "user", content: "hi" }], {
      model: "claude-haiku-4-5",
    });

    expect(result.content).toBe("hello world");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const firstBody = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    const retryBody = JSON.parse(fetchMock.mock.calls[1][1].body as string);
    expect(firstBody.model).toBe("claude-haiku-4-5");
    expect(retryBody.model).toBe("@cf/zai-org/glm-5.2");
  });

  it("routes straight to the free-tier model once the org is known unsubscribed", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(createJsonResponse(MODEL_GATE_BODY, 403))
      .mockImplementation(async () => createJsonResponse(SUCCESS_BODY));
    const { service } = createService(fetchMock);

    // First call learns "unsubscribed" from the gate's 403.
    await service.prompt([{ role: "user", content: "hi" }], {
      model: "claude-haiku-4-5",
    });
    // Second call must not burn a round trip on the gate.
    await service.prompt([{ role: "user", content: "hi" }], {
      model: "claude-haiku-4-5",
    });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    const thirdBody = JSON.parse(fetchMock.mock.calls[2][1].body as string);
    expect(thirdBody.model).toBe("@cf/zai-org/glm-5.2");
  });

  it("forgets the learned subscription state when the organization changes", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(createJsonResponse(MODEL_GATE_BODY, 403))
      .mockImplementation(async () => createJsonResponse(SUCCESS_BODY));
    const { service, emitAuthState } = createService(fetchMock);

    await service.prompt([{ role: "user", content: "hi" }], {
      model: "claude-haiku-4-5",
    });
    emitAuthState("org-2");
    await service.prompt([{ role: "user", content: "hi" }], {
      model: "claude-haiku-4-5",
    });

    const bodyAfterSwitch = JSON.parse(
      fetchMock.mock.calls[2][1].body as string,
    );
    expect(bodyAfterSwitch.model).toBe("claude-haiku-4-5");
  });

  it("keeps the learned subscription state across same-org auth changes", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(createJsonResponse(MODEL_GATE_BODY, 403))
      .mockImplementation(async () => createJsonResponse(SUCCESS_BODY));
    const { service, emitAuthState } = createService(fetchMock);

    await service.prompt([{ role: "user", content: "hi" }], {
      model: "claude-haiku-4-5",
    });
    emitAuthState("org-1");
    await service.prompt([{ role: "user", content: "hi" }], {
      model: "claude-haiku-4-5",
    });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    const bodyAfterRefresh = JSON.parse(
      fetchMock.mock.calls[2][1].body as string,
    );
    expect(bodyAfterRefresh.model).toBe("@cf/zai-org/glm-5.2");
  });

  it("does not retry non-gate 403s on the free-tier model", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        createJsonResponse(
          { detail: "Product 'posthog_code' requires OAuth authentication" },
          403,
        ),
      );
    const { service } = createService(fetchMock);

    await expect(
      service.prompt([{ role: "user", content: "hi" }]),
    ).rejects.toMatchObject({ statusCode: 403 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("throws a timeout LlmGatewayError when the request aborts via the internal timeout", async () => {
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          reject(new DOMException("aborted", "AbortError"));
        });
      });
    });
    const { service } = createService(fetchMock as never);

    const promise = service.prompt([{ role: "user", content: "hi" }], {
      timeoutMs: 5,
    });

    await expect(promise).rejects.toBeInstanceOf(LlmGatewayError);
    await expect(promise).rejects.toMatchObject({ type: "timeout" });
  });
});

describe("LlmGatewayService.fetchUsage", () => {
  const USAGE_BODY = {
    product: "code",
    user_id: 1,
    sustained: {
      used_percent: 10,
      reset_at: "2026-01-01T00:00:00.000Z",
      exceeded: false,
    },
    burst: {
      used_percent: 20,
      reset_at: "2026-01-01T00:00:00.000Z",
      exceeded: false,
    },
    is_rate_limited: false,
  };

  it("returns the schema-parsed usage payload from Django", async () => {
    const fetchMock = vi.fn().mockResolvedValue(createJsonResponse(USAGE_BODY));
    const { service } = createService(fetchMock);

    const usage = await service.fetchUsage();

    expect(usage.product).toBe("code");
    expect(usage.sustained.used_percent).toBe(10);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_HOST}/api/projects/42/desktop/usage/`,
      { headers: { "X-PostHog-Project-Id": "42" } },
    );
  });

  it("falls back to the legacy usage URL once per org after a 404", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(createJsonResponse({ detail: "nope" }, 404))
      .mockImplementation(async () => createJsonResponse(USAGE_BODY));
    const { service } = createService(fetchMock);

    await service.fetchUsage();
    await service.fetchUsage();

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      `${API_HOST}/api/projects/42/desktop/usage/`,
      `${API_HOST}/gateway/usage`,
      `${API_HOST}/gateway/usage`,
    ]);
  });

  it("re-probes Django after the organization changes", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(createJsonResponse({}, 404))
      .mockImplementation(async () => createJsonResponse(USAGE_BODY));
    const { service, emitAuthState } = createService(fetchMock);

    await service.fetchUsage();
    emitAuthState("org-2");
    await service.fetchUsage();

    expect(fetchMock.mock.calls.at(-1)?.[0]).toBe(
      `${API_HOST}/api/projects/42/desktop/usage/`,
    );
  });

  it("strips the Django body's extra is_pro field", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      createJsonResponse({
        ...USAGE_BODY,
        product: "posthog_code",
        is_pro: false,
        ai_credits: { exhausted: false, used_usd: 1.5, limit_usd: 100 },
        code_usage_subscribed: true,
        billing_period_end: "2026-10-01T00:00:00Z",
      }),
    );
    const { service } = createService(fetchMock);

    const usage = await service.fetchUsage();

    expect(usage).not.toHaveProperty("is_pro");
    expect(usage.billing_period_end).toBe("2026-10-01T00:00:00Z");
  });

  it("throws a usage_error LlmGatewayError on non-ok response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(createJsonResponse({}, 503));
    const { service } = createService(fetchMock);

    await expect(service.fetchUsage()).rejects.toMatchObject({
      type: "usage_error",
      statusCode: 503,
    });
  });

  it("parses the usage-based billing fields when present", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      createJsonResponse({
        ...USAGE_BODY,
        ai_credits: { exhausted: true, used_usd: 12.4, limit_usd: 50 },
        code_usage_subscribed: true,
      }),
    );
    const { service } = createService(fetchMock);

    const usage = await service.fetchUsage();

    expect(usage.ai_credits?.exhausted).toBe(true);
    expect(usage.ai_credits?.used_usd).toBe(12.4);
    expect(usage.ai_credits?.limit_usd).toBe(50);
    expect(usage.code_usage_subscribed).toBe(true);
  });

  it("parses ai_credits with null spend numbers from an unsynced org", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      createJsonResponse({
        ...USAGE_BODY,
        ai_credits: { exhausted: false, used_usd: null, limit_usd: null },
      }),
    );
    const { service } = createService(fetchMock);

    const usage = await service.fetchUsage();

    expect(usage.ai_credits?.exhausted).toBe(false);
    expect(usage.ai_credits?.used_usd).toBeNull();
    expect(usage.ai_credits?.limit_usd).toBeNull();
  });

  it("parses the optional Desktop component breakdown without rounding integers", async () => {
    const breakdown = {
      token_credits: 1_234,
      compute_credits: 67,
      cpu_millicore_seconds: 9_876_543_210,
      memory_mib_seconds: 7_654_321_098,
    };
    const fetchMock = vi.fn().mockResolvedValue(
      createJsonResponse({
        ...USAGE_BODY,
        ai_credits: {
          exhausted: false,
          used_usd: 13.01,
          limit_usd: 20,
          breakdown,
        },
      }),
    );
    const { service } = createService(fetchMock);

    const usage = await service.fetchUsage();

    expect(usage.ai_credits?.breakdown).toEqual(breakdown);
  });

  it("feeds code_usage_subscribed into helper model routing", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        createJsonResponse({ ...USAGE_BODY, code_usage_subscribed: false }),
      )
      .mockResolvedValue(createJsonResponse(SUCCESS_BODY));
    const { service } = createService(fetchMock);

    await service.fetchUsage();
    await service.prompt([{ role: "user", content: "hi" }], {
      model: "claude-haiku-4-5",
    });

    const promptBody = JSON.parse(fetchMock.mock.calls[1][1].body as string);
    expect(promptBody.model).toBe("@cf/zai-org/glm-5.2");
  });
});

describe("LlmGatewayService.prompt on the Go gateway", () => {
  it("posts to the Go gateway with the session token and a properties blob", async () => {
    const authenticatedFetch = vi.fn();
    const goFetch = vi.fn().mockResolvedValue(createJsonResponse(SUCCESS_BODY));
    const { service } = createService(authenticatedFetch, {
      route: GO_ROUTE,
      fetch: goFetch,
    });

    await service.prompt([{ role: "user", content: "hi" }], {
      model: "claude-haiku-4-5",
      posthogProperties: { ai_stage: "title", $ai_span_name: "title" },
    });

    expect(authenticatedFetch).not.toHaveBeenCalled();
    const [url, init] = goFetch.mock.calls[0];
    expect(url).toBe("https://ai-gateway.us.posthog.com/v1/messages");
    expect(init.redirect).toBe("error");
    expect(init.headers.Authorization).toBe("Bearer phe_one");
    expect(init.headers).not.toHaveProperty("X-PostHog-Project-Id");
    expect(JSON.parse(init.headers["X-PostHog-Properties"])).toEqual({
      ai_stage: "title",
      ai_product: "posthog_code",
      team_id: 7,
    });
    expect(JSON.parse(init.body).model).toBe("claude-haiku-4-5");
  });

  it("picks the free-tier model from the pin without a round trip", async () => {
    const goFetch = vi.fn().mockResolvedValue(createJsonResponse(SUCCESS_BODY));
    const { service } = createService(vi.fn(), {
      route: {
        ...GO_ROUTE,
        plan: "free",
        allowedModels: ["zai-org/glm-5.3", "@cf/zai-org/glm-5.2"],
      },
      fetch: goFetch,
    });

    await service.prompt([{ role: "user", content: "hi" }], {
      model: "claude-haiku-4-5",
    });

    expect(goFetch).toHaveBeenCalledTimes(1);
    expect(JSON.parse(goFetch.mock.calls[0][1].body).model).toBe(
      "@cf/zai-org/glm-5.2",
    );
  });

  it("falls back to the first allowed model when the free model is not pinned", async () => {
    const goFetch = vi.fn().mockResolvedValue(createJsonResponse(SUCCESS_BODY));
    const { service } = createService(vi.fn(), {
      route: { ...GO_ROUTE, plan: "free", allowedModels: ["zai-org/glm-5.3"] },
      fetch: goFetch,
    });

    await service.prompt([{ role: "user", content: "hi" }]);

    expect(JSON.parse(goFetch.mock.calls[0][1].body).model).toBe(
      "zai-org/glm-5.3",
    );
  });

  it.each([
    [
      "a 401",
      createJsonResponse({ error: { message: "bad token" } }, 401),
      "unauthorized",
    ],
    [
      "a token cap 402",
      new Response(
        JSON.stringify({
          type: "error",
          error: { type: "billing_error", message: "admission rejected" },
        }),
        {
          status: 402,
          headers: { "X-PostHog-Denial": "token_cap_exceeded" },
        },
      ),
      "token_cap_exceeded",
    ],
  ])("re-mints once and retries after %s", async (_label, refusal, reason) => {
    const goFetch = vi
      .fn()
      .mockResolvedValueOnce(refusal)
      .mockResolvedValue(createJsonResponse(SUCCESS_BODY));
    const remint = vi.fn().mockResolvedValue({ ...GO_ROUTE, token: "phe_two" });
    const { service } = createService(vi.fn(), {
      route: GO_ROUTE,
      fetch: goFetch,
      remint,
    });

    const result = await service.prompt([{ role: "user", content: "hi" }]);

    expect(result.content).toBe("hello world");
    expect(remint).toHaveBeenCalledWith(reason, "phe_one", 42);
    expect(goFetch.mock.calls[1][1].headers.Authorization).toBe(
      "Bearer phe_two",
    );
  });

  it("surfaces a cap refusal after a 401 re-mint without trying legacy", async () => {
    const goFetch = vi
      .fn()
      .mockResolvedValueOnce(new Response("{}", { status: 401 }))
      .mockResolvedValueOnce(
        new Response("{}", {
          status: 402,
          headers: { "X-PostHog-Denial": "token_cap_exceeded" },
        }),
      );
    const remint = vi.fn().mockResolvedValue({ ...GO_ROUTE, token: "phe_two" });
    const legacyFetch = vi.fn();
    const { service, gatewayTokens } = createService(legacyFetch, {
      route: GO_ROUTE,
      fetch: goFetch,
      remint,
    });

    await expect(
      service.prompt([{ role: "user", content: "hi" }]),
    ).rejects.toMatchObject({ statusCode: 402 });
    expect(remint).toHaveBeenCalledTimes(1);
    expect(legacyFetch).not.toHaveBeenCalled();
    expect(gatewayTokens.fallBack).not.toHaveBeenCalled();
  });

  it("surfaces the original refusal when the re-mint rejects", async () => {
    const goFetch = vi
      .fn()
      .mockResolvedValueOnce(
        createJsonResponse({ error: { message: "bad token" } }, 401),
      );
    const remint = vi.fn().mockRejectedValue(new Error("mint exploded"));
    const { service } = createService(vi.fn(), {
      route: GO_ROUTE,
      fetch: goFetch,
      remint,
    });

    await expect(
      service.prompt([{ role: "user", content: "hi" }]),
    ).rejects.toMatchObject({ name: "LlmGatewayError", statusCode: 401 });
    expect(goFetch).toHaveBeenCalledTimes(1);
  });

  it("keeps the requested model when the pin is null or empty", async () => {
    for (const allowedModels of [null, []]) {
      const goFetch = vi
        .fn()
        .mockResolvedValue(createJsonResponse(SUCCESS_BODY));
      const { service } = createService(vi.fn(), {
        route: { ...GO_ROUTE, allowedModels },
        fetch: goFetch,
      });

      await service.prompt([{ role: "user", content: "hi" }], {
        model: "claude-haiku-4-5",
      });

      expect(JSON.parse(goFetch.mock.calls[0][1].body).model).toBe(
        "claude-haiku-4-5",
      );
    }
  });

  it.each([
    [401, "unauthorized", true],
    [402, "token_cap_exceeded", false],
  ] as const)(
    "surfaces a 401 on the token re-minted after a %s, falling back only for a 401 pair",
    async (firstStatus, reason, fallsBack) => {
      const refusal = (status: number) =>
        new Response("{}", {
          status,
          headers:
            status === 402 ? { "X-PostHog-Denial": "token_cap_exceeded" } : {},
        });
      const goFetch = vi
        .fn()
        .mockResolvedValueOnce(refusal(firstStatus))
        .mockResolvedValueOnce(refusal(401));
      const remint = vi
        .fn()
        .mockResolvedValue({ ...GO_ROUTE, token: "phe_two" });
      const legacyFetch = vi.fn();
      const { service, gatewayTokens } = createService(legacyFetch, {
        route: GO_ROUTE,
        fetch: goFetch,
        remint,
      });

      await expect(
        service.prompt([{ role: "user", content: "hi" }]),
      ).rejects.toMatchObject({ statusCode: 401 });
      expect(goFetch).toHaveBeenCalledTimes(2);
      expect(remint).toHaveBeenCalledWith(reason, "phe_one", 42);
      expect(remint).toHaveBeenCalledTimes(1);
      expect(legacyFetch).not.toHaveBeenCalled();
      if (fallsBack) {
        expect(gatewayTokens.fallBack).toHaveBeenCalledWith("phe_two", 42);
      } else {
        expect(gatewayTokens.fallBack).not.toHaveBeenCalled();
      }
    },
  );

  it("does not retry an org spend refusal and does not use the legacy model-gate retry", async () => {
    const goFetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: "credit_bucket_exhausted",
            message: "limit reached",
          },
        }),
        { status: 402 },
      ),
    );
    const remint = vi.fn();
    const { service } = createService(vi.fn(), {
      route: GO_ROUTE,
      fetch: goFetch,
      remint,
    });

    await expect(
      service.prompt([{ role: "user", content: "hi" }]),
    ).rejects.toMatchObject({
      statusCode: 402,
      code: "credit_bucket_exhausted",
    });
    expect(remint).not.toHaveBeenCalled();
    expect(goFetch).toHaveBeenCalledTimes(1);
  });

  it("surfaces the second refusal when the re-mint yields nothing", async () => {
    const goFetch = vi
      .fn()
      .mockResolvedValue(
        createJsonResponse({ error: { message: "bad" } }, 401),
      );
    const { service } = createService(vi.fn(), {
      route: GO_ROUTE,
      fetch: goFetch,
      remint: vi.fn().mockResolvedValue(null),
    });

    await expect(
      service.prompt([{ role: "user", content: "hi" }]),
    ).rejects.toMatchObject({ statusCode: 401 });
    expect(goFetch).toHaveBeenCalledTimes(1);
  });

  it("refuses a helper prompt while the credit bucket is exhausted, without legacy", async () => {
    const authenticatedFetch = vi.fn();
    const goFetch = vi.fn();
    const { service } = createService(authenticatedFetch, {
      route: {
        mode: "blocked",
        reason: "credit_bucket_exhausted",
        detail: "Your organization has reached its PostHog Desktop usage limit",
      },
      fetch: goFetch,
    });

    const error = await service
      .prompt([{ role: "user", content: "hi" }])
      .catch((e: unknown) => e);

    expect(error).toMatchObject({
      statusCode: 402,
      code: "credit_bucket_exhausted",
    });
    expect(classifyGatewayLimitError((error as Error).message)).toBe(
      "org_limit",
    );
    expect(authenticatedFetch).not.toHaveBeenCalled();
    expect(goFetch).not.toHaveBeenCalled();
  });
});

describe("LlmGatewayService.fetchUsage and the blocked route", () => {
  it.each([
    [false, 1],
    [true, 0],
  ])(
    "clears a blocked route when exhausted is %s",
    async (exhausted, calls) => {
      const fetchMock = vi.fn().mockResolvedValue(
        createJsonResponse({
          product: "posthog_code",
          user_id: 1,
          sustained: {
            used_percent: 0,
            reset_at: "2026-01-01T00:00:00Z",
            exceeded: false,
          },
          burst: {
            used_percent: 0,
            reset_at: "2026-01-01T00:00:00Z",
            exceeded: false,
          },
          is_rate_limited: exhausted,
          ai_credits: { exhausted, used_usd: 1, limit_usd: 2 },
        }),
      );
      const { service, gatewayTokens } = createService(fetchMock);

      await service.fetchUsage();

      expect(gatewayTokens.clearBlocked).toHaveBeenCalledTimes(calls);
    },
  );
});
