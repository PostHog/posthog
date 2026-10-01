import type { RootLogger } from "@posthog/di/logger";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthService } from "../auth/auth";
import type { AuthState } from "../auth/schemas";
import {
  GATEWAY_BLOCKED_RECHECK_MS,
  GATEWAY_LEGACY_RECHECK_MS,
  GATEWAY_MINT_TIMEOUT_MS,
  GATEWAY_NOT_ROLLED_OUT_RECHECK_MS,
  GATEWAY_REFRESH_RETRY_MS,
  GATEWAY_REMINT_MIN_INTERVAL_MS,
  GATEWAY_TOKEN_MIN_REFRESH_SKEW_MS,
  GATEWAY_TOKEN_REFRESH_SKEW_MS,
  GatewayTokenService,
} from "./gateway-token";
import type { GatewayTokenHost, LlmGatewayHost } from "./identifiers";

const API_HOST = "https://us.posthog.com";
const MINT_URL = `${API_HOST}/api/projects/42/desktop/gateway_token/`;

function minted(token: string, expiresInMs = 3_600_000) {
  return {
    enabled: true,
    token,
    expires_at: new Date(Date.now() + expiresInMs).toISOString(),
    cap_usd: "200",
    gateway_url: "https://ai-gateway.us.posthog.com",
    product: "posthog_code",
    team_id: 7,
    plan: "paid",
    allowed_models: ["claude-opus-5"],
    product_models: ["claude-opus-5", "gpt-6-sol"],
  };
}

function json(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function baseState(overrides: Partial<AuthState> = {}): AuthState {
  return {
    status: "authenticated",
    bootstrapComplete: true,
    cloudRegion: "us",
    orgProjectsMap: {},
    currentOrgId: "org-1",
    currentProjectId: 42,
    desktopAccess: { projectId: 42, status: "allowed", reason: null },
    needsScopeReauth: false,
    sessionType: "persistent",
    sessionExpiresAt: null,
    ...overrides,
  };
}

function setup(
  options: { config?: Partial<GatewayTokenHost>; state?: AuthState } = {},
) {
  let state = options.state ?? baseState();
  let accountKey: string | null = "user-1";
  let sessionEpoch: number | null = 1;
  const listeners: Array<(state: AuthState) => void> = [];
  const reportDesktopAccessBlocked = vi.fn();
  const authService = {
    getState: () => state,
    on: (_event: string, listener: (state: AuthState) => void) => {
      listeners.push(listener);
    },
    getCachedAccountKey: () => accountKey,
    getSessionEpoch: () => sessionEpoch,
    reportDesktopAccessBlocked,
  } as unknown as AuthService;

  const mintResponses: Array<
    (init?: RequestInit) => Response | Promise<Response>
  > = [];
  const authenticatedFetch = vi.fn(async (url: string, init?: RequestInit) => {
    const next = mintResponses.shift();
    if (!next) throw new Error(`unexpected fetch ${url}`);
    return next(init);
  });
  const host: LlmGatewayHost = {
    getValidAccessToken: vi
      .fn()
      .mockResolvedValue({ accessToken: "pha_x", apiHost: API_HOST }),
    authenticatedFetch,
    messagesUrl: () => "",
    usageUrl: () => "",
    legacyUsageUrl: () => "",
    defaultModel: "m",
  };
  const log = { debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() };
  const logger = { ...log, scope: () => log } as unknown as RootLogger;
  const service = new GatewayTokenService(
    host,
    { goEnabled: true, override: null, ...options.config },
    authService,
    logger,
  );
  const mintCalls = () =>
    authenticatedFetch.mock.calls.filter(([url]) => url === MINT_URL).length;
  return {
    service,
    host,
    mintResponses,
    authenticatedFetch,
    mintCalls,
    reportDesktopAccessBlocked,
    setAccountKey(next: string | null) {
      accountKey = next;
    },
    setSessionEpoch(next: number | null) {
      sessionEpoch = next;
    },
    setState(next: AuthState) {
      state = next;
      for (const listener of listeners) listener(next);
    },
  };
}

describe("GatewayTokenService.getRoute", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-09-23T12:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("mints once and serves the Go route from the cache", async () => {
    const t = setup();
    t.mintResponses.push(() => json(minted("phe_one"), 201));

    const first = await t.service.getRoute();
    const second = await t.service.getRoute(42);

    expect(first).toMatchObject({
      mode: "go",
      gatewayUrl: "https://ai-gateway.us.posthog.com",
      token: "phe_one",
      teamId: 7,
      plan: "paid",
      allowedModels: ["claude-opus-5"],
      productModels: ["claude-opus-5", "gpt-6-sol"],
      projectId: 42,
      source: "mint",
    });
    expect(second).toBe(first);
    expect(t.mintCalls()).toBe(1);
    const [, init] = t.authenticatedFetch.mock.calls[0];
    expect(init?.method).toBe("POST");
    expect(init?.redirect).toBe("error");
  });

  it("shares one in-flight mint between concurrent callers", async () => {
    const t = setup();
    t.mintResponses.push(() => json(minted("phe_one"), 201));

    const [a, b] = await Promise.all([
      t.service.getRoute(),
      t.service.getRoute(),
    ]);

    expect(a).toEqual(b);
    expect(t.mintCalls()).toBe(1);
  });

  it.each([
    [
      200,
      { enabled: false, reason: "unconfigured" },
      "unconfigured",
      GATEWAY_LEGACY_RECHECK_MS,
    ],
    [
      200,
      { enabled: false, reason: "not_rolled_out" },
      "not_rolled_out",
      GATEWAY_NOT_ROLLED_OUT_RECHECK_MS,
    ],
    [
      403,
      { enabled: false, reason: "desktop_access_blocked" },
      "desktop_access_blocked",
      GATEWAY_LEGACY_RECHECK_MS,
    ],
    [
      402,
      { enabled: false, reason: "payment_required" },
      "payment_required",
      GATEWAY_LEGACY_RECHECK_MS,
    ],
    [404, { detail: "Not found." }, "http_404", GATEWAY_LEGACY_RECHECK_MS],
    [429, { detail: "org deactivated" }, "http_429", GATEWAY_LEGACY_RECHECK_MS],
    [503, null, "http_503", GATEWAY_LEGACY_RECHECK_MS],
  ])(
    "treats a %s as legacy and re-checks after the negative cache",
    async (status, body, reason, recheckMs) => {
      const t = setup();
      t.mintResponses.push(() => json(body, status));
      t.mintResponses.push(() => json(minted("phe_one"), 201));

      expect(await t.service.getRoute()).toEqual({ mode: "legacy", reason });
      vi.setSystemTime(Date.now() + recheckMs - 1);
      expect(await t.service.getRoute()).toMatchObject({ mode: "legacy" });
      expect(t.mintCalls()).toBe(1);
      vi.setSystemTime(Date.now() + 2);
      expect(await t.service.getRoute()).toEqual({ mode: "legacy", reason });
      expect(t.mintCalls()).toBe(2);
      await vi.waitFor(async () =>
        expect(await t.service.getRoute()).toMatchObject({ mode: "go" }),
      );
      expect(t.mintCalls()).toBe(2);
    },
  );

  it("serves a known refusal to callers while its re-check is in flight", async () => {
    const t = setup();
    t.mintResponses.push(() =>
      json({ enabled: false, reason: "not_rolled_out" }, 200),
    );
    t.mintResponses.push(() => new Promise<Response>(() => undefined));

    await t.service.getRoute();
    vi.setSystemTime(Date.now() + GATEWAY_NOT_ROLLED_OUT_RECHECK_MS);
    await t.service.getRoute();
    await vi.waitFor(() => expect(t.mintCalls()).toBe(2));

    expect(await t.service.getRoute()).toEqual({
      mode: "legacy",
      reason: "not_rolled_out",
    });
  });

  it("waits for the re-check when a session start asks for it", async () => {
    const t = setup();
    t.mintResponses.push(() =>
      json({ enabled: false, reason: "not_rolled_out" }, 200),
    );
    t.mintResponses.push(() => json(minted("phe_one"), 201));

    await t.service.getRoute();
    vi.setSystemTime(Date.now() + GATEWAY_NOT_ROLLED_OUT_RECHECK_MS);

    expect(await t.service.getRoute(42, { awaitRecheck: true })).toMatchObject({
      mode: "go",
      token: "phe_one",
    });
  });

  it.each([
    [
      "a session start on a legacy route",
      { enabled: false, reason: "not_rolled_out" },
      200,
      GATEWAY_NOT_ROLLED_OUT_RECHECK_MS,
      { awaitRecheck: true },
    ],
    [
      "any caller on a blocked route",
      { enabled: false, reason: "credit_bucket_exhausted" },
      402,
      GATEWAY_BLOCKED_RECHECK_MS,
      {},
    ],
  ])(
    "joins a re-check already in flight for %s",
    async (_label, refusal, status, recheckMs, options) => {
      const t = setup();
      t.mintResponses.push(() => json(refusal, status));
      let release: (response: Response) => void = () => undefined;
      t.mintResponses.push(
        () =>
          new Promise<Response>((resolve) => {
            release = resolve;
          }),
      );

      await t.service.getRoute();
      vi.setSystemTime(Date.now() + recheckMs);
      void t.service.getRoute(42, { awaitRecheck: false });
      await vi.waitFor(() => expect(t.mintCalls()).toBe(2));
      const joined = t.service.getRoute(42, options);
      release(json(minted("phe_one"), 201));

      expect(await joined).toMatchObject({ mode: "go", token: "phe_one" });
    },
  );

  it("waits for a due blocked re-check instead of refusing again", async () => {
    const t = setup();
    t.mintResponses.push(() =>
      json({ enabled: false, reason: "credit_bucket_exhausted" }, 402),
    );
    t.mintResponses.push(() => json(minted("phe_one"), 201));

    await t.service.getRoute();
    vi.setSystemTime(Date.now() + GATEWAY_BLOCKED_RECHECK_MS);

    expect(await t.service.getRoute()).toMatchObject({
      mode: "go",
      token: "phe_one",
    });
  });

  it("treats an exhausted credit bucket as final, not as legacy", async () => {
    const t = setup();
    const sentence =
      "Your organization has reached its PostHog Desktop usage limit";
    t.mintResponses.push(() =>
      json(
        { enabled: false, reason: "credit_bucket_exhausted", detail: sentence },
        402,
      ),
    );
    t.mintResponses.push(() => json(minted("phe_one"), 201));

    expect(await t.service.getRoute()).toEqual({
      mode: "blocked",
      reason: "credit_bucket_exhausted",
      detail: sentence,
    });
    vi.setSystemTime(Date.now() + GATEWAY_BLOCKED_RECHECK_MS - 1);
    expect(await t.service.getRoute()).toMatchObject({ mode: "blocked" });
    expect(
      await t.service.remint("unauthorized", "phe_none", undefined),
    ).toBeNull();
    expect(t.mintCalls()).toBe(1);

    t.service.clearBlocked();
    expect(await t.service.getRoute()).toMatchObject({ mode: "go" });
  });

  it.each([
    [403, { enabled: false, reason: "email_unverified" }, "email_unverified"],
    [
      403,
      {
        detail: "Organization is deactivated.",
        code: "organization_deactivated",
      },
      "organization_deactivated",
    ],
    [429, { enabled: false, reason: "throttled" }, "throttled"],
    [
      503,
      { enabled: false, reason: "desktop_access_unavailable" },
      "desktop_access_unavailable",
    ],
    [503, { enabled: false, reason: "mint_failed" }, "mint_failed"],
  ])(
    "keeps a %s refusal on legacy with its reason",
    async (status, body, reason) => {
      const t = setup();
      t.mintResponses.push(() => json(body, status));

      expect(await t.service.getRoute()).toEqual({ mode: "legacy", reason });
    },
  );

  it("feeds a desktop access denial into the auth state", async () => {
    const t = setup();
    const access = { allowed: false, reason: "startup_plan" };
    t.mintResponses.push(() =>
      json({ enabled: false, reason: "desktop_access_blocked", access }, 403),
    );

    expect(await t.service.getRoute()).toEqual({
      mode: "legacy",
      reason: "desktop_access_blocked",
    });
    expect(t.reportDesktopAccessBlocked).toHaveBeenCalledWith(42, access);
  });

  it("falls back to legacy when the mint request fails", async () => {
    const t = setup();
    t.mintResponses.push(() => {
      throw new Error("offline");
    });

    expect(await t.service.getRoute()).toEqual({
      mode: "legacy",
      reason: "mint_failed",
    });
  });

  it.each([
    "https://evil.example",
    "https://llm.posthog.com",
    "http://ai-gateway.us.posthog.com",
    "http://localhost:3308",
    "https://ai-gateway.us.posthog.com/v1",
    "https://ai-gateway.dev.posthog.dev",
  ])("refuses a token naming %s", async (gatewayUrl) => {
    const t = setup();
    t.mintResponses.push(() =>
      json({ ...minted("phe_bad"), gateway_url: gatewayUrl }, 201),
    );

    expect(await t.service.getRoute()).toEqual({
      mode: "legacy",
      reason: "invalid_gateway_url",
    });
  });

  it("reads the token's lifetime against the server clock", async () => {
    const t = setup();
    // The local clock runs 10 minutes ahead of the server.
    const serverNow = Date.now() - 10 * 60_000;
    t.mintResponses.push(
      () =>
        new Response(
          JSON.stringify({
            ...minted("phe_one"),
            expires_at: new Date(serverNow + 5 * 60_000).toISOString(),
          }),
          {
            status: 201,
            headers: { date: new Date(serverNow).toUTCString() },
          },
        ),
    );

    const route = await t.service.getRoute();

    expect(route).toMatchObject({ token: "phe_one" });
    expect((route as { expiresAt: number }).expiresAt).toBeGreaterThan(
      Date.now() + 4 * 60_000,
    );
    expect(await t.service.getRoute()).toBe(route);
    expect(t.mintCalls()).toBe(1);
  });

  it("pins the re-check, re-mint and refresh windows", () => {
    expect(GATEWAY_LEGACY_RECHECK_MS).toBe(600_000);
    expect(GATEWAY_NOT_ROLLED_OUT_RECHECK_MS).toBe(1_800_000);
    expect(GATEWAY_BLOCKED_RECHECK_MS).toBe(1_800_000);
    expect(GATEWAY_REMINT_MIN_INTERVAL_MS).toBe(5_000);
    expect(GATEWAY_REFRESH_RETRY_MS).toBe(30_000);
    expect(GATEWAY_TOKEN_REFRESH_SKEW_MS).toBe(120_000);
    expect(GATEWAY_TOKEN_MIN_REFRESH_SKEW_MS).toBe(30_000);
    expect(GATEWAY_MINT_TIMEOUT_MS).toBe(15_000);
  });

  it.each([
    ["a 2-minute", 2 * 60_000, 30_000],
    ["a 5-minute", 5 * 60_000, 30_000],
    ["a 10-minute", 10 * 60_000, 60_000],
    ["an hourly", 60 * 60_000, 120_000],
  ])(
    "refreshes %s token a tenth of its lifetime early, within bounds",
    async (_label, lifetimeMs, skewMs) => {
      const t = setup();
      t.mintResponses.push(() => json(minted("phe_one", lifetimeMs), 201));
      t.mintResponses.push(() => json(minted("phe_two", lifetimeMs), 201));
      const start = Date.now();

      await t.service.getRoute();
      vi.setSystemTime(start + lifetimeMs - skewMs - 1);
      expect(await t.service.getRoute()).toMatchObject({ token: "phe_one" });
      expect(t.mintCalls()).toBe(1);
      vi.setSystemTime(start + lifetimeMs - skewMs + 1);
      expect(await t.service.getRoute()).toMatchObject({ token: "phe_one" });
      await vi.waitFor(() => expect(t.mintCalls()).toBe(2));
    },
  );

  it("rejects a 201 whose expiry is not a date", async () => {
    const t = setup();
    t.mintResponses.push(() =>
      json({ ...minted("phe_one"), expires_at: "soon" }, 201),
    );

    expect(await t.service.getRoute()).toEqual({
      mode: "legacy",
      reason: "invalid_expiry",
    });
    expect(await t.service.getRoute()).toEqual({
      mode: "legacy",
      reason: "invalid_expiry",
    });
    expect(t.mintCalls()).toBe(1);
  });

  it("gives up on a mint that does not answer in time", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout"] });
    const t = setup();
    t.mintResponses.push(
      (init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new Error("aborted")),
          );
        }),
    );

    const pending = t.service.getRoute();
    await vi.advanceTimersByTimeAsync(GATEWAY_MINT_TIMEOUT_MS - 1);
    let settled = false;
    void pending.then(() => {
      settled = true;
    });
    await Promise.resolve();
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1);

    expect(await pending).toEqual({ mode: "legacy", reason: "mint_failed" });
  });

  it("gives up on a mint whose body does not arrive in time", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setTimeout", "clearTimeout"] });
    const t = setup();
    t.mintResponses.push(
      (init) =>
        new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              init?.signal?.addEventListener("abort", () =>
                controller.error(new Error("aborted")),
              );
            },
          }),
          { status: 201 },
        ),
    );

    const pending = t.service.getRoute();
    await vi.advanceTimersByTimeAsync(GATEWAY_MINT_TIMEOUT_MS);

    expect(await pending).toEqual({
      mode: "legacy",
      reason: "invalid_mint_response",
    });
  });

  it("rejects a 201 that does not match the contract", async () => {
    const t = setup();
    t.mintResponses.push(() => json({ ...minted("sk-not-phe") }, 201));

    expect(await t.service.getRoute()).toEqual({
      mode: "legacy",
      reason: "invalid_mint_response",
    });
  });

  it("refreshes in the background inside the skew and blocks once expired", async () => {
    const t = setup();
    t.mintResponses.push(() => json(minted("phe_one", 10 * 60_000), 201));
    t.mintResponses.push(() => json(minted("phe_two"), 201));
    t.mintResponses.push(() => json(minted("phe_three"), 201));

    await t.service.getRoute();
    vi.setSystemTime(Date.now() + 10 * 60_000 - 60_000 + 1);
    const during = await t.service.getRoute();
    expect(during).toMatchObject({ token: "phe_one" });
    await vi.waitFor(async () =>
      expect(await t.service.getRoute()).toMatchObject({ token: "phe_two" }),
    );

    vi.setSystemTime(Date.now() + 3_600_000 + 1);
    expect(await t.service.getRoute()).toMatchObject({ token: "phe_three" });
  });

  it.each([
    ["a network error", () => Promise.reject(new Error("offline"))],
    ["a 503", () => json(null, 503)],
    [
      "a flag-off refusal",
      () => json({ enabled: false, reason: "not_rolled_out" }, 200),
    ],
  ])(
    "keeps the unexpired token when the early refresh hits %s",
    async (_label, failure) => {
      const t = setup();
      t.mintResponses.push(() => json(minted("phe_one", 10 * 60_000), 201));
      t.mintResponses.push(failure);
      t.mintResponses.push(() => json(minted("phe_two"), 201));

      await t.service.getRoute();
      vi.setSystemTime(Date.now() + 10 * 60_000 - 60_000 + 1);
      expect(await t.service.getRoute()).toMatchObject({ token: "phe_one" });
      await vi.waitFor(() => expect(t.mintCalls()).toBe(2));
      await new Promise((resolve) => setTimeout(resolve, 20));
      expect(await t.service.getRoute()).toMatchObject({ token: "phe_one" });
      expect(t.mintCalls()).toBe(2);

      vi.setSystemTime(Date.now() + GATEWAY_REFRESH_RETRY_MS);
      await t.service.getRoute();
      await vi.waitFor(async () =>
        expect(await t.service.getRoute()).toMatchObject({ token: "phe_two" }),
      );
    },
  );

  it("replaces the unexpired token when the early refresh finds the bucket empty", async () => {
    const t = setup();
    t.mintResponses.push(() => json(minted("phe_one", 10 * 60_000), 201));
    t.mintResponses.push(() =>
      json({ enabled: false, reason: "credit_bucket_exhausted" }, 402),
    );

    await t.service.getRoute();
    vi.setSystemTime(Date.now() + 10 * 60_000 - 60_000 + 1);
    await t.service.getRoute();
    await vi.waitFor(async () =>
      expect(await t.service.getRoute()).toMatchObject({ mode: "blocked" }),
    );
  });

  it("answers legacy without minting on a host that cannot reach Go", async () => {
    const t = setup({ config: { goEnabled: false } });

    expect(await t.service.getRoute()).toEqual({
      mode: "legacy",
      reason: "host_unsupported",
    });
    expect(t.authenticatedFetch).not.toHaveBeenCalled();
  });

  it("answers legacy with no selected project", async () => {
    const t = setup({ state: baseState({ currentProjectId: null }) });

    expect(await t.service.getRoute()).toEqual({
      mode: "legacy",
      reason: "no_project",
    });
  });

  it("uses the dev override without minting", async () => {
    const t = setup({
      config: {
        override: { url: "http://localhost:3308", token: "phe_dev" },
      },
    });

    expect(await t.service.getRoute()).toMatchObject({
      mode: "go",
      gatewayUrl: "http://localhost:3308",
      token: "phe_dev",
      source: "override",
      allowedModels: null,
      productModels: [],
    });
    expect(
      await t.service.remint("unauthorized", "phe_dev", undefined),
    ).toBeNull();
    expect(t.authenticatedFetch).not.toHaveBeenCalled();
  });
});

describe("GatewayTokenService.remint", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-09-23T12:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  async function primed() {
    const t = setup();
    t.mintResponses.push(() => json(minted("phe_one"), 201));
    await t.service.getRoute();
    vi.setSystemTime(Date.now() + GATEWAY_REMINT_MIN_INTERVAL_MS);
    return t;
  }

  it("dedupes concurrent 401 re-mints into one mint", async () => {
    const t = await primed();
    t.mintResponses.push(() => json(minted("phe_two"), 201));

    const [a, b] = await Promise.all([
      t.service.remint("unauthorized", "phe_one", undefined),
      t.service.remint("unauthorized", "phe_one", undefined),
    ]);

    expect(a).toMatchObject({ token: "phe_two" });
    expect(b).toMatchObject({ token: "phe_two" });
    expect(t.mintCalls()).toBe(2);
  });

  it("returns the current route when another caller already replaced the token", async () => {
    const t = await primed();
    t.mintResponses.push(() => json(minted("phe_two"), 201));
    await t.service.remint("unauthorized", "phe_one", undefined);

    const again = await t.service.remint("unauthorized", "phe_one", undefined);

    expect(again).toMatchObject({ token: "phe_two" });
    expect(t.mintCalls()).toBe(2);
  });

  it("re-mints once per token for token_cap_exceeded", async () => {
    const t = await primed();
    t.mintResponses.push(() => json(minted("phe_two"), 201));

    expect(
      await t.service.remint("token_cap_exceeded", "phe_one", undefined),
    ).toMatchObject({
      token: "phe_two",
    });
    vi.setSystemTime(Date.now() + GATEWAY_REMINT_MIN_INTERVAL_MS);
    t.mintResponses.push(() => json(minted("phe_three"), 201));
    expect(
      await t.service.remint("token_cap_exceeded", "phe_two", undefined),
    ).toMatchObject({
      token: "phe_three",
    });
    expect(
      await t.service.remint("token_cap_exceeded", "phe_two", undefined),
    ).toMatchObject({
      token: "phe_three",
    });
    expect(t.mintCalls()).toBe(3);
  });

  it("refuses a second cap re-mint for the same token", async () => {
    const t = await primed();
    t.mintResponses.push(() =>
      json({ enabled: false, reason: "not_rolled_out" }, 200),
    );

    expect(
      await t.service.remint("token_cap_exceeded", "phe_one", undefined),
    ).toBeNull();
    // Past the minimum interval, so only the per-token rule refuses.
    vi.setSystemTime(Date.now() + GATEWAY_REMINT_MIN_INTERVAL_MS);
    expect(
      await t.service.remint("token_cap_exceeded", "phe_one", undefined),
    ).toBeNull();
    expect(t.mintCalls()).toBe(2);
  });

  it("returns null when the identity changes while a re-mint waits on a mint", async () => {
    const t = await primed();
    let release: (response: Response) => void = () => undefined;
    t.mintResponses.push(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    );

    const pending = t.service.remint("unauthorized", "phe_one", undefined);
    await vi.waitFor(() => expect(t.mintCalls()).toBe(2));
    t.setAccountKey("user-2");
    t.setState(baseState({ currentOrgId: "org-2" }));
    release(json(minted("phe_two"), 201));

    expect(await pending).toBeNull();
    t.mintResponses.push(() => json(minted("phe_three"), 201));
    expect(await t.service.getRoute()).toMatchObject({ token: "phe_three" });
  });

  it("does not re-mint once signed out", async () => {
    const t = await primed();
    t.setState(baseState({ status: "anonymous", currentProjectId: null }));

    expect(await t.service.remint("unauthorized", "phe_one", 42)).toBeNull();
    expect(t.mintCalls()).toBe(1);
  });

  it("still re-mints for the same account after a project switch", async () => {
    const t = await primed();
    t.setState(baseState({ currentProjectId: 43 }));
    t.mintResponses.push(() => json(minted("phe_two"), 201));

    expect(await t.service.remint("unauthorized", "phe_one", 42)).toMatchObject(
      { token: "phe_two" },
    );
  });

  it("still re-mints on a 401 for a token a routine mint issued", async () => {
    const t = await primed();
    t.mintResponses.push(() => json(minted("phe_two"), 201));
    await t.service.remint("token_cap_exceeded", "phe_one", undefined);
    vi.setSystemTime(Date.now() + GATEWAY_REMINT_MIN_INTERVAL_MS);
    t.mintResponses.push(() => json(minted("phe_three"), 201));

    expect(
      await t.service.remint("unauthorized", "phe_two", undefined),
    ).toMatchObject({ token: "phe_three" });
  });

  it("keeps the cap re-mint when the minimum interval skips it", async () => {
    const t = setup();
    t.mintResponses.push(() => json(minted("phe_one"), 201));
    await t.service.getRoute();

    expect(
      await t.service.remint("token_cap_exceeded", "phe_one", undefined),
    ).toBeNull();
    vi.setSystemTime(Date.now() + GATEWAY_REMINT_MIN_INTERVAL_MS);
    t.mintResponses.push(() => json(minted("phe_two"), 201));
    expect(
      await t.service.remint("token_cap_exceeded", "phe_one", undefined),
    ).toMatchObject({ token: "phe_two" });
  });

  it("falls back to legacy when Go refuses the re-minted token too", async () => {
    const t = await primed();
    t.mintResponses.push(() => json(minted("phe_two"), 201));
    await t.service.remint("unauthorized", "phe_one", undefined);

    t.service.fallBack("phe_two", undefined);

    expect(await t.service.getRoute()).toEqual({
      mode: "legacy",
      reason: "gateway_unauthorized",
    });
    vi.setSystemTime(Date.now() + GATEWAY_LEGACY_RECHECK_MS - 1);
    expect(await t.service.getRoute()).toMatchObject({ mode: "legacy" });
    expect(t.mintCalls()).toBe(2);
    t.mintResponses.push(() => json(minted("phe_three"), 201));
    vi.setSystemTime(Date.now() + 1);
    await t.service.getRoute();
    await vi.waitFor(async () =>
      expect(await t.service.getRoute()).toMatchObject({ token: "phe_three" }),
    );
  });

  it("falls back only the named project", async () => {
    const t = await primed();
    t.mintResponses.push(() => json(minted("phe_other"), 201));
    expect(await t.service.getRoute(43)).toMatchObject({ token: "phe_other" });

    t.service.fallBack("phe_other", 43);

    expect(await t.service.getRoute(43)).toEqual({
      mode: "legacy",
      reason: "gateway_unauthorized",
    });
    expect(await t.service.getRoute(42)).toMatchObject({ token: "phe_one" });
  });

  it("ignores a fallback for a token that is no longer current", async () => {
    const t = await primed();
    t.mintResponses.push(() => json(minted("phe_two"), 201));
    await t.service.remint("unauthorized", "phe_one", undefined);

    t.service.fallBack("phe_one", 42);

    expect(await t.service.getRoute()).toMatchObject({ token: "phe_two" });
  });

  it("falls back instead of re-minting on a 401 inside the minimum interval", async () => {
    const t = setup();
    t.mintResponses.push(() => json(minted("phe_one"), 201));
    await t.service.getRoute();

    expect(
      await t.service.remint("unauthorized", "phe_one", undefined),
    ).toBeNull();
    expect(await t.service.getRoute()).toEqual({
      mode: "legacy",
      reason: "gateway_unauthorized",
    });
    expect(t.mintCalls()).toBe(1);
  });

  it("serves the newer token to a 401 on an older one inside the minimum interval", async () => {
    const t = await primed();
    t.mintResponses.push(() => json(minted("phe_two"), 201));
    await t.service.remint("token_cap_exceeded", "phe_one", undefined);

    expect(
      await t.service.remint("unauthorized", "phe_one", undefined),
    ).toMatchObject({ token: "phe_two" });
    expect(await t.service.getRoute()).toMatchObject({ token: "phe_two" });
  });
});

describe("GatewayTokenService identity changes", () => {
  it.each([
    ["project", { currentProjectId: 43 }],
    ["organization", { currentOrgId: "org-2" }],
    ["region", { cloudRegion: "eu" as const }],
  ])("drops cached tokens when the %s changes", async (_label, change) => {
    const t = setup();
    t.mintResponses.push(() => json(minted("phe_one"), 201));
    t.mintResponses.push(() => json(minted("phe_two"), 201));
    await t.service.getRoute(42);

    t.setState(baseState(change));
    t.setState(baseState());

    expect(await t.service.getRoute(42)).toMatchObject({ token: "phe_two" });
  });

  it("drops cached tokens when the account changes", async () => {
    const t = setup();
    t.mintResponses.push(() => json(minted("phe_one"), 201));
    t.mintResponses.push(() => json(minted("phe_two"), 201));
    await t.service.getRoute(42);

    t.setAccountKey("user-2");
    t.setState(baseState());

    expect(await t.service.getRoute(42)).toMatchObject({ token: "phe_two" });
  });

  it("drops cached tokens on a sign-in over a live session when the account lookup failed", async () => {
    const t = setup();
    t.mintResponses.push(() => json(minted("phe_one"), 201));
    t.mintResponses.push(() => json(minted("phe_two"), 201));
    await t.service.getRoute(42);

    t.setAccountKey(null);
    t.setSessionEpoch(2);
    t.setState(baseState());

    expect(await t.service.getRoute(42)).toMatchObject({ token: "phe_two" });
  });

  it("drops cached tokens when the session type changes", async () => {
    const t = setup();
    t.mintResponses.push(() => json(minted("phe_one"), 201));
    t.mintResponses.push(() => json(minted("phe_two"), 201));
    await t.service.getRoute(42);

    t.setState(baseState({ sessionType: "impersonated" }));

    expect(await t.service.getRoute(42)).toMatchObject({ token: "phe_two" });
  });

  it("keeps tokens across unrelated state updates", async () => {
    const t = setup();
    t.mintResponses.push(() => json(minted("phe_one"), 201));
    await t.service.getRoute();

    t.setState(
      baseState({
        desktopAccess: { projectId: 42, status: "checking", reason: null },
      }),
    );
    t.setAccountKey(null);
    t.setState(baseState({ status: "restoring" }));
    t.setState(baseState());

    expect(await t.service.getRoute()).toMatchObject({ token: "phe_one" });
    expect(t.mintCalls()).toBe(1);
  });

  it("answers legacy without minting while signed out", async () => {
    const t = setup();
    t.mintResponses.push(() => json(minted("phe_one"), 201));
    await t.service.getRoute();

    t.setState(baseState({ status: "anonymous", currentProjectId: 42 }));

    expect(await t.service.getRoute(42)).toEqual({
      mode: "legacy",
      reason: "signed_out",
    });
    expect(t.mintCalls()).toBe(1);
  });

  it("answers legacy before any identity exists", async () => {
    const t = setup({ state: baseState({ status: "restoring" }) });

    expect(await t.service.getRoute(42)).toEqual({
      mode: "legacy",
      reason: "signed_out",
    });
    expect(t.mintCalls()).toBe(0);
  });

  describe("discards a mint that lands for an older identity", () => {
    it.each([
      [
        "a sign-out",
        (t: ReturnType<typeof setup>) =>
          t.setState(
            baseState({ status: "anonymous", currentProjectId: null }),
          ),
      ],
      [
        "an account switch",
        (t: ReturnType<typeof setup>) => {
          t.setAccountKey("user-2");
          t.setState(baseState());
        },
      ],
      [
        "a region switch",
        (t: ReturnType<typeof setup>) =>
          t.setState(baseState({ cloudRegion: "eu" })),
      ],
    ])("after %s", async (_label, change) => {
      const t = setup();
      let release: (response: Response) => void = () => undefined;
      t.mintResponses.push(
        () =>
          new Promise<Response>((resolve) => {
            release = resolve;
          }),
      );

      const pending = t.service.getRoute(42);
      await vi.waitFor(() => expect(t.mintCalls()).toBe(1));
      change(t);
      release(json(minted("phe_one"), 201));

      expect(await pending).toEqual({
        mode: "legacy",
        reason: "identity_changed",
      });
      t.setState(baseState());
      t.mintResponses.push(() => json(minted("phe_two"), 201));
      expect(await t.service.getRoute(42)).toMatchObject({ token: "phe_two" });
    });

    it("skips the mint request when the identity changes while reading the OAuth token", async () => {
      const t = setup();
      vi.mocked(t.host.getValidAccessToken).mockImplementationOnce(async () => {
        t.setState(baseState({ status: "anonymous", currentProjectId: null }));
        return { accessToken: "pha_x", apiHost: API_HOST };
      });

      expect(await t.service.getRoute()).toEqual({
        mode: "legacy",
        reason: "identity_changed",
      });
      expect(t.mintCalls()).toBe(0);
    });

    it("does not report a desktop access denial for another identity", async () => {
      const t = setup();
      t.mintResponses.push(() => {
        t.setAccountKey("user-2");
        t.setState(baseState());
        return json({ enabled: false, reason: "desktop_access_blocked" }, 403);
      });

      await t.service.getRoute();
      expect(t.reportDesktopAccessBlocked).not.toHaveBeenCalled();
    });
  });

  it("hands a mint that raced a failed account lookup to its caller", async () => {
    const t = setup();
    let release: (response: Response) => void = () => undefined;
    t.mintResponses.push(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    );

    const pending = t.service.getRoute(42);
    await vi.waitFor(() => expect(t.mintCalls()).toBe(1));
    t.setAccountKey(null);
    t.setState(baseState({ currentOrgId: null }));
    release(json(minted("phe_one"), 201));

    expect(await pending).toMatchObject({ mode: "go", token: "phe_one" });
  });

  it("hands a mint that raced a project switch to its caller without caching it", async () => {
    const t = setup();
    let release: (response: Response) => void = () => undefined;
    t.mintResponses.push(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    );

    const pending = t.service.getRoute(42);
    await vi.waitFor(() => expect(t.mintCalls()).toBe(1));
    t.setState(baseState({ currentProjectId: 43 }));
    release(json(minted("phe_one"), 201));

    expect(await pending).toMatchObject({ mode: "go", token: "phe_one" });
    t.mintResponses.push(() => json(minted("phe_two"), 201));
    expect(await t.service.getRoute(42)).toMatchObject({ token: "phe_two" });
  });
});
