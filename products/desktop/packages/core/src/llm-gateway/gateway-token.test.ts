import type { RootLogger } from "@posthog/di/logger";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthService } from "../auth/auth";
import type { AuthState } from "../auth/schemas";
import {
  GATEWAY_ACTION_RECHECK_MS,
  GATEWAY_BLOCKED_RECHECK_MS,
  GATEWAY_MINT_TIMEOUT_MS,
  GATEWAY_REMINT_MIN_INTERVAL_MS,
  GATEWAY_THROTTLED_RECHECK_MS,
  GATEWAY_TOKEN_MIN_REFRESH_SKEW_MS,
  GATEWAY_TOKEN_REFRESH_SKEW_MS,
  GATEWAY_TRANSIENT_MAX_RECHECK_MS,
  GATEWAY_TRANSIENT_RECHECK_MS,
  GatewayTokenService,
  transientRecheckMs,
} from "./gateway-token";
import type { GatewayTokenHost, LlmGatewayHost } from "./identifiers";

const API_HOST = "https://us.posthog.com";
const MINT_URL = `${API_HOST}/api/projects/42/desktop/gateway_token/`;
const TRANSIENT = "Couldn't reach PostHog AI. Retrying shortly.";
const UNAVAILABLE = "PostHog AI isn't available for this project right now.";
const SIGN_IN = "Sign in to PostHog again to use PostHog AI.";

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
    // Jitter at its ceiling, so a first transient re-check is exactly 30s.
    vi.spyOn(Math, "random").mockReturnValue(1);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
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
      403,
      UNAVAILABLE,
      GATEWAY_ACTION_RECHECK_MS,
    ],
    [
      200,
      { enabled: false, reason: "not_rolled_out" },
      "not_rolled_out",
      403,
      UNAVAILABLE,
      GATEWAY_ACTION_RECHECK_MS,
    ],
    [
      403,
      { enabled: false, reason: "desktop_access_blocked" },
      "desktop_access_blocked",
      403,
      "PostHog Desktop access is required.",
      GATEWAY_BLOCKED_RECHECK_MS,
    ],
    [
      403,
      { enabled: false, reason: "email_unverified" },
      "email_unverified",
      403,
      "Verify your email to use PostHog AI.",
      GATEWAY_ACTION_RECHECK_MS,
    ],
    // Django's billing-limit 429: without its row this would read as throttled.
    [
      429,
      {
        type: "billing_limit",
        code: "organization_deactivated",
        error: "Organization is deactivated.",
      },
      "organization_deactivated",
      403,
      UNAVAILABLE,
      GATEWAY_ACTION_RECHECK_MS,
    ],
    [
      403,
      { enabled: false, reason: "oauth_required", detail: "Sign in." },
      "oauth_required",
      401,
      "Sign in.",
      GATEWAY_ACTION_RECHECK_MS,
    ],
    [
      429,
      { enabled: false, reason: "throttled", detail: "Try later." },
      "throttled",
      429,
      "Too many PostHog AI sign-in attempts. Try again in a few minutes.",
      GATEWAY_THROTTLED_RECHECK_MS,
    ],
    [
      503,
      { enabled: false, reason: "mint_failed", detail: "mint failed" },
      "mint_failed",
      503,
      TRANSIENT,
      GATEWAY_TRANSIENT_RECHECK_MS,
    ],
    [
      403,
      { enabled: false, reason: "unauthorized", detail: "Not this project." },
      "unauthorized",
      401,
      "Not this project.",
      GATEWAY_ACTION_RECHECK_MS,
    ],
    [
      403,
      { enabled: false, reason: "blocked", detail: "No AI for you." },
      "blocked",
      403,
      "No AI for you.",
      GATEWAY_BLOCKED_RECHECK_MS,
    ],
    [
      403,
      { enabled: false, reason: "org_deactivated" },
      "org_deactivated",
      403,
      UNAVAILABLE,
      GATEWAY_ACTION_RECHECK_MS,
    ],
    [
      200,
      { enabled: false, reason: "credit_state_unknown" },
      "credit_state_unknown",
      503,
      TRANSIENT,
      GATEWAY_TRANSIENT_RECHECK_MS,
    ],
    [
      402,
      { enabled: false, reason: "payment_required" },
      "payment_required",
      402,
      UNAVAILABLE,
      GATEWAY_ACTION_RECHECK_MS,
    ],
    [
      401,
      { enabled: false, reason: "token_revoked", detail: "Revoked." },
      "token_revoked",
      401,
      "Revoked.",
      GATEWAY_ACTION_RECHECK_MS,
    ],
    [
      429,
      { type: "billing_limit", code: "usage_limit_reached" },
      "usage_limit_reached",
      429,
      "Too many PostHog AI sign-in attempts. Try again in a few minutes.",
      GATEWAY_THROTTLED_RECHECK_MS,
    ],
    [
      404,
      { detail: "Not found." },
      "http_404",
      403,
      "Not found.",
      GATEWAY_ACTION_RECHECK_MS,
    ],
    // `constructor` is an inherited key, not a table entry.
    [
      403,
      { enabled: false, reason: "constructor" },
      "constructor",
      403,
      UNAVAILABLE,
      GATEWAY_ACTION_RECHECK_MS,
    ],
    [503, null, "http_503", 503, TRANSIENT, GATEWAY_TRANSIENT_RECHECK_MS],
  ])(
    "blocks a %s refusal with its reason and re-mints after the re-check",
    async (status, body, reason, blockedStatus, detail, recheckMs) => {
      const t = setup();
      t.mintResponses.push(() => json(body, status));
      t.mintResponses.push(() => json(minted("phe_one"), 201));

      expect(await t.service.getRoute()).toEqual({
        mode: "blocked",
        reason,
        detail,
        status: blockedStatus,
      });
      vi.setSystemTime(Date.now() + recheckMs - 1);
      expect(await t.service.getRoute()).toMatchObject({ mode: "blocked" });
      expect(t.mintCalls()).toBe(1);
      vi.setSystemTime(Date.now() + 2);
      expect(await t.service.getRoute()).toMatchObject({ mode: "go" });
      expect(t.mintCalls()).toBe(2);
    },
  );

  it("serves a known refusal while its re-check is in flight to a caller that will not wait", async () => {
    const t = setup();
    t.mintResponses.push(() =>
      json({ enabled: false, reason: "not_rolled_out" }, 200),
    );
    t.mintResponses.push(() => new Promise<Response>(() => undefined));

    await t.service.getRoute();
    vi.setSystemTime(Date.now() + GATEWAY_ACTION_RECHECK_MS);
    await t.service.getRoute(42, { awaitRecheck: false });
    await vi.waitFor(() => expect(t.mintCalls()).toBe(2));

    expect(await t.service.getRoute(42, { awaitRecheck: false })).toMatchObject(
      { mode: "blocked", reason: "not_rolled_out" },
    );
  });

  it("waits for a due re-check by default", async () => {
    const t = setup();
    t.mintResponses.push(() =>
      json({ enabled: false, reason: "not_rolled_out" }, 200),
    );
    t.mintResponses.push(() => json(minted("phe_one"), 201));

    await t.service.getRoute();
    vi.setSystemTime(Date.now() + GATEWAY_ACTION_RECHECK_MS);

    expect(await t.service.getRoute()).toMatchObject({
      mode: "go",
      token: "phe_one",
    });
  });

  it.each([
    [
      "a caller on a refused route",
      { enabled: false, reason: "not_rolled_out" },
      200,
      GATEWAY_ACTION_RECHECK_MS,
      {},
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

  it("treats an exhausted credit bucket as a 402 that only clears on a refill", async () => {
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
      status: 402,
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

  it("keeps a refusal other than an exhausted bucket when usage reports a refill", async () => {
    const t = setup();
    t.mintResponses.push(() =>
      json({ enabled: false, reason: "throttled" }, 429),
    );

    await t.service.getRoute();
    t.service.clearBlocked();

    expect(await t.service.getRoute()).toMatchObject({
      mode: "blocked",
      reason: "throttled",
    });
    expect(t.mintCalls()).toBe(1);
  });

  it("backs off on consecutive transient refusals and resets after a mint", async () => {
    const t = setup();
    t.mintResponses.push(() => json(null, 503));
    t.mintResponses.push(() => json(null, 503));
    t.mintResponses.push(() => json(minted("phe_one"), 201));
    t.mintResponses.push(() => json(null, 503));
    t.mintResponses.push(() => json(minted("phe_two"), 201));

    await t.service.getRoute();
    vi.setSystemTime(Date.now() + GATEWAY_TRANSIENT_RECHECK_MS);
    expect(await t.service.getRoute()).toMatchObject({ mode: "blocked" });
    expect(t.mintCalls()).toBe(2);
    vi.setSystemTime(Date.now() + 2 * GATEWAY_TRANSIENT_RECHECK_MS - 1);
    expect(await t.service.getRoute()).toMatchObject({ mode: "blocked" });
    expect(t.mintCalls()).toBe(2);
    vi.setSystemTime(Date.now() + 1);
    expect(await t.service.getRoute()).toMatchObject({ token: "phe_one" });

    // The mint reset the count, so this wait is 30s.
    vi.setSystemTime(Date.now() + 3_600_000);
    expect(await t.service.getRoute()).toMatchObject({ mode: "blocked" });
    expect(t.mintCalls()).toBe(4);
    vi.setSystemTime(Date.now() + GATEWAY_TRANSIENT_RECHECK_MS);
    expect(await t.service.getRoute()).toMatchObject({ token: "phe_two" });
  });

  it("backs off when the early refresh fails twice in a row", async () => {
    const t = setup();
    // An hourly token refreshes 2 minutes early, leaving room for 30s + 60s.
    t.mintResponses.push(() => json(minted("phe_one"), 201));
    t.mintResponses.push(() => json(null, 503));
    t.mintResponses.push(() => json(null, 503));
    t.mintResponses.push(() => json(minted("phe_two"), 201));

    await t.service.getRoute();
    vi.setSystemTime(Date.now() + 3_600_000 - 120_000);
    await t.service.getRoute();
    await vi.waitFor(() => expect(t.mintCalls()).toBe(2));
    // Let the refused refresh settle and schedule its re-check.
    await new Promise((resolve) => setTimeout(resolve, 20));
    vi.setSystemTime(Date.now() + GATEWAY_TRANSIENT_RECHECK_MS);
    await t.service.getRoute();
    await vi.waitFor(() => expect(t.mintCalls()).toBe(3));
    await new Promise((resolve) => setTimeout(resolve, 20));

    vi.setSystemTime(Date.now() + 2 * GATEWAY_TRANSIENT_RECHECK_MS - 1_000);
    expect(await t.service.getRoute()).toMatchObject({ token: "phe_one" });
    expect(t.mintCalls()).toBe(3);
    vi.setSystemTime(Date.now() + 1_000);
    await t.service.getRoute();
    await vi.waitFor(async () =>
      expect(await t.service.getRoute()).toMatchObject({ token: "phe_two" }),
    );
  });

  it("shortens a transient re-check by the jitter draw", async () => {
    const t = setup();
    vi.spyOn(Math, "random").mockReturnValue(0);
    t.mintResponses.push(() => json(null, 503));
    t.mintResponses.push(() => json(minted("phe_one"), 201));

    await t.service.getRoute();
    vi.setSystemTime(Date.now() + GATEWAY_TRANSIENT_RECHECK_MS / 2 - 1);
    expect(await t.service.getRoute()).toMatchObject({ mode: "blocked" });
    vi.setSystemTime(Date.now() + 1);
    expect(await t.service.getRoute()).toMatchObject({ token: "phe_one" });
  });

  it("feeds a desktop access denial into the auth state", async () => {
    const t = setup();
    const access = { allowed: false, reason: "startup_plan" };
    t.mintResponses.push(() =>
      json({ enabled: false, reason: "desktop_access_blocked", access }, 403),
    );

    expect(await t.service.getRoute()).toMatchObject({
      mode: "blocked",
      reason: "desktop_access_blocked",
    });
    expect(t.reportDesktopAccessBlocked).toHaveBeenCalledWith(42, access);
  });

  it("blocks briefly when the mint request fails", async () => {
    const t = setup();
    t.mintResponses.push(() => {
      throw new Error("offline");
    });

    expect(await t.service.getRoute()).toEqual({
      mode: "blocked",
      reason: "mint_failed",
      detail: TRANSIENT,
      status: 503,
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

    expect(await t.service.getRoute()).toMatchObject({
      mode: "blocked",
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
    expect(GATEWAY_ACTION_RECHECK_MS).toBe(600_000);
    expect(GATEWAY_BLOCKED_RECHECK_MS).toBe(1_800_000);
    expect(GATEWAY_THROTTLED_RECHECK_MS).toBe(300_000);
    expect(GATEWAY_TRANSIENT_RECHECK_MS).toBe(30_000);
    expect(GATEWAY_REMINT_MIN_INTERVAL_MS).toBe(5_000);
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

    expect(await t.service.getRoute()).toMatchObject({
      mode: "blocked",
      reason: "invalid_expiry",
    });
    expect(await t.service.getRoute()).toMatchObject({
      mode: "blocked",
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

    expect(await pending).toMatchObject({
      mode: "blocked",
      reason: "mint_failed",
    });
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

    expect(await pending).toMatchObject({
      mode: "blocked",
      reason: "invalid_mint_response",
    });
  });

  it("rejects a 201 that does not match the contract", async () => {
    const t = setup();
    t.mintResponses.push(() => json({ ...minted("sk-not-phe") }, 201));

    expect(await t.service.getRoute()).toMatchObject({
      mode: "blocked",
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
    // Non-transient refusals wait for expiry, 59,999ms after the refresh.
    [
      "a network error",
      () => Promise.reject(new Error("offline")),
      GATEWAY_TRANSIENT_RECHECK_MS,
    ],
    ["a 503", () => json(null, 503), GATEWAY_TRANSIENT_RECHECK_MS],
    [
      "a flag-off refusal",
      () => json({ enabled: false, reason: "not_rolled_out" }, 200),
      60_000 - 1,
    ],
  ])(
    "keeps the unexpired token when the early refresh hits %s",
    async (_label, failure, retryAfterMs) => {
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

      // A second of slack: only Date is faked, so real milliseconds still pass.
      vi.setSystemTime(Date.now() + retryAfterMs - 1_000);
      expect(await t.service.getRoute()).toMatchObject({ token: "phe_one" });
      expect(t.mintCalls()).toBe(2);
      vi.setSystemTime(Date.now() + 1_000);
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

  it("blocks without minting on a host that cannot reach Go", async () => {
    const t = setup({ config: { goEnabled: false } });

    expect(await t.service.getRoute()).toEqual({
      mode: "blocked",
      reason: "host_unsupported",
      detail: "PostHog AI helpers aren't available in the web app yet.",
      status: 403,
    });
    expect(t.authenticatedFetch).not.toHaveBeenCalled();
  });

  it("blocks with no selected project", async () => {
    const t = setup({ state: baseState({ currentProjectId: null }) });

    expect(await t.service.getRoute()).toEqual({
      mode: "blocked",
      reason: "no_project",
      detail: "Select a project to use PostHog AI.",
      status: 403,
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
    // Jitter at its ceiling, so a first transient re-check is exactly 30s.
    vi.spyOn(Math, "random").mockReturnValue(1);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
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

  it("blocks briefly when Go refuses the re-minted token too", async () => {
    const t = await primed();
    t.mintResponses.push(() => json(minted("phe_two"), 201));
    await t.service.remint("unauthorized", "phe_one", undefined);

    t.service.fallBack("phe_two", undefined);

    expect(await t.service.getRoute()).toMatchObject({
      mode: "blocked",
      reason: "gateway_unauthorized",
      status: 503,
    });
    vi.setSystemTime(Date.now() + GATEWAY_TRANSIENT_RECHECK_MS - 1);
    expect(await t.service.getRoute()).toMatchObject({ mode: "blocked" });
    expect(t.mintCalls()).toBe(2);
    t.mintResponses.push(() => json(minted("phe_three"), 201));
    vi.setSystemTime(Date.now() + 1);
    expect(await t.service.getRoute()).toMatchObject({ token: "phe_three" });
  });

  it("schedules a Go 401 block through the jittered backoff", async () => {
    vi.spyOn(Math, "random").mockReturnValue(0);
    const t = await primed();
    t.service.fallBack("phe_one", undefined);

    vi.setSystemTime(Date.now() + GATEWAY_TRANSIENT_RECHECK_MS / 2 - 1);
    expect(await t.service.getRoute()).toMatchObject({ mode: "blocked" });
    t.mintResponses.push(() => json(minted("phe_two"), 201));
    vi.setSystemTime(Date.now() + 1);
    expect(await t.service.getRoute()).toMatchObject({ token: "phe_two" });
  });

  it("blocks only the named project", async () => {
    const t = await primed();
    t.mintResponses.push(() => json(minted("phe_other"), 201));
    expect(await t.service.getRoute(43)).toMatchObject({ token: "phe_other" });

    t.service.fallBack("phe_other", 43);

    expect(await t.service.getRoute(43)).toMatchObject({
      mode: "blocked",
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

  it("blocks instead of re-minting on a 401 inside the minimum interval", async () => {
    const t = setup();
    t.mintResponses.push(() => json(minted("phe_one"), 201));
    await t.service.getRoute();

    expect(
      await t.service.remint("unauthorized", "phe_one", undefined),
    ).toBeNull();
    expect(await t.service.getRoute()).toMatchObject({
      mode: "blocked",
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

  it("blocks without minting while signed out", async () => {
    const t = setup();
    t.mintResponses.push(() => json(minted("phe_one"), 201));
    await t.service.getRoute();

    t.setState(baseState({ status: "anonymous", currentProjectId: 42 }));

    expect(await t.service.getRoute(42)).toEqual({
      mode: "blocked",
      reason: "signed_out",
      detail: SIGN_IN,
      status: 401,
    });
    expect(t.mintCalls()).toBe(1);
  });

  it("blocks before any identity exists", async () => {
    const t = setup({ state: baseState({ status: "restoring" }) });

    expect(await t.service.getRoute(42)).toMatchObject({
      mode: "blocked",
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

      expect(await pending).toMatchObject({
        mode: "blocked",
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

      expect(await t.service.getRoute()).toMatchObject({
        mode: "blocked",
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

describe("transientRecheckMs", () => {
  it.each([
    [1, 1, GATEWAY_TRANSIENT_RECHECK_MS],
    [1, 0, GATEWAY_TRANSIENT_RECHECK_MS / 2],
    [2, 1, 2 * GATEWAY_TRANSIENT_RECHECK_MS],
    [3, 1, 4 * GATEWAY_TRANSIENT_RECHECK_MS],
    [20, 1, GATEWAY_TRANSIENT_MAX_RECHECK_MS],
  ])(
    "waits up to the doubled 30s for failure %i (random %s)",
    (failures, random, expected) => {
      expect(transientRecheckMs(failures, random)).toBe(expected);
    },
  );
});
