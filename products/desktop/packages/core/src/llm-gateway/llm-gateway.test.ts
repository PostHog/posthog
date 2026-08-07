import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthService } from "../auth/auth";
import type {
  LlmGatewayAuth,
  LlmGatewayEndpoints,
  LlmGatewayHost,
  LlmGatewayLogger,
} from "./identifiers";
import { LlmGatewayError, LlmGatewayService } from "./llm-gateway";

const API_HOST = "https://app.example.com";

function createJsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function createService(
  authenticatedFetch: LlmGatewayAuth["authenticatedFetch"],
) {
  const auth: LlmGatewayAuth = {
    getValidAccessToken: vi
      .fn()
      .mockResolvedValue({ accessToken: "tok", apiHost: API_HOST }),
    authenticatedFetch,
  };

  const endpoints: LlmGatewayEndpoints = {
    messagesUrl: (host) => `${host}/gateway/v1/messages`,
    usageUrl: (host) => `${host}/gateway/usage`,
    defaultModel: "claude-default",
  };

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
    getState: () => ({ currentOrgId: "org-1" }),
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

  const service = new LlmGatewayService(host, logger, authService);
  return { service, auth, endpoints, log, emitAuthState };
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

  // The free-tier model gate's 403 body, as the gateway serves it.
  const MODEL_GATE_BODY = {
    error: {
      message:
        "Model 'claude-haiku-4-5' needs a paid PostHog plan. Models available on the free tier: @cf/zai-org/glm-5.2. Add a payment method to your organization to unlock all models. (rate_limit)",
      type: "permission_error",
      code: "model_gate",
    },
  };

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
    is_pro: true,
  };

  it("returns the schema-parsed usage payload", async () => {
    const fetchMock = vi.fn().mockResolvedValue(createJsonResponse(USAGE_BODY));
    const { service } = createService(fetchMock);

    const usage = await service.fetchUsage();

    expect(usage.product).toBe("code");
    expect(usage.is_pro).toBe(true);
    expect(usage.sustained.used_percent).toBe(10);
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
