import { NotAuthenticatedError } from "@posthog/shared";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthService } from "../auth/auth";
import type { UsageHost } from "./identifiers";
import { UsageMonitorEvent } from "./monitor-schemas";
import type { UsageOutput } from "./schemas";
import { UsageMonitorService } from "./usage-monitor";

type ActivitySlice = Pick<
  UsageHost,
  "onLlmActivity" | "offLlmActivity" | "hasActiveSessions"
>;

interface MockActivityMonitor extends ActivitySlice {
  fireLlmActivity(): void;
}

function makeActivityMonitor(opts?: {
  hasActiveSessions?: boolean;
}): MockActivityMonitor {
  const listeners = new Set<() => void>();
  return {
    onLlmActivity: (l) => listeners.add(l),
    offLlmActivity: (l) => listeners.delete(l),
    hasActiveSessions: () => opts?.hasActiveSessions ?? false,
    fireLlmActivity: () => {
      for (const l of [...listeners]) l();
    },
  };
}

type ThresholdSlice = Pick<
  UsageHost,
  "getThresholdsSeen" | "setThresholdsSeen"
>;

let persisted: Record<string, string> = {};

function makeThresholdStore(): ThresholdSlice {
  return {
    getThresholdsSeen: () => ({ ...persisted }),
    setThresholdsSeen: (v) => {
      persisted = { ...v };
    },
  };
}

interface ScopedLog {
  debug: ReturnType<typeof vi.fn>;
  info: ReturnType<typeof vi.fn>;
  warn: ReturnType<typeof vi.fn>;
  error: ReturnType<typeof vi.fn>;
}

let lastScopedLog: ScopedLog;

function makeLogger() {
  const log = { debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() };
  lastScopedLog = log;
  return { ...log, scope: () => log };
}

type GatewaySlice = Pick<UsageHost, "fetchUsage">;

type AuthStatus = "anonymous" | "authenticated" | "restoring";
interface EmittedAuthState {
  currentOrgId: string | null;
  status: AuthStatus;
}

let emitAuthState: (currentOrgId: string | null, status?: AuthStatus) => void =
  () => {};

function makeAuthService(): AuthService {
  const listeners = new Set<(state: EmittedAuthState) => void>();
  let currentStatus: AuthStatus = "authenticated";
  emitAuthState = (currentOrgId, status = "authenticated") => {
    currentStatus = status;
    for (const listener of [...listeners]) {
      listener({ currentOrgId, status });
    }
  };
  return {
    getState: () => ({ currentOrgId: "org-1", status: currentStatus }),
    on: (_event: string, listener: (state: EmittedAuthState) => void) =>
      listeners.add(listener),
  } as unknown as AuthService;
}

function makeService(
  gateway: GatewaySlice,
  activity: ActivitySlice,
): UsageMonitorService {
  const host: UsageHost = {
    ...gateway,
    ...activity,
    ...makeThresholdStore(),
  };
  return new UsageMonitorService(host, makeLogger(), makeAuthService());
}

function makeUsage(overrides?: {
  burstPercent?: number;
  sustainedPercent?: number;
  billingPeriodEnd?: string | null;
  burstResetAt?: string;
  sustainedResetAt?: string;
  isPro?: boolean;
}): UsageOutput {
  return {
    product: "posthog_code",
    user_id: 42,
    is_rate_limited: false,
    is_pro: overrides?.isPro ?? false,
    code_usage_subscribed: false,
    billing_period_end:
      overrides?.billingPeriodEnd === undefined
        ? null
        : overrides.billingPeriodEnd,
    burst: {
      used_percent: overrides?.burstPercent ?? 0,
      reset_at: overrides?.burstResetAt ?? "2026-05-25T16:00:00.000Z",
      exceeded: false,
    },
    sustained: {
      used_percent: overrides?.sustainedPercent ?? 0,
      reset_at: overrides?.sustainedResetAt ?? "2026-06-01T00:00:00.000Z",
      exceeded: false,
    },
  };
}

function mockGateway(usage: UsageOutput | null): GatewaySlice {
  return {
    fetchUsage: vi.fn().mockResolvedValue(usage),
  } as unknown as GatewaySlice;
}

describe("UsageMonitorService", () => {
  let service: UsageMonitorService;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-25T12:00:00.000Z"));
    persisted = {};
  });

  afterEach(() => {
    service?.stop();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("emits at 75% but not again on the next poll for the same anchor", async () => {
    const events: unknown[] = [];
    const gateway = mockGateway(makeUsage({ burstPercent: 78 }));
    service = makeService(gateway, makeActivityMonitor());
    service.on(UsageMonitorEvent.ThresholdCrossed, (e) => events.push(e));

    await service.fetchOnce();
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({
      bucket: "burst",
      threshold: 75,
      usedPercent: 78,
    });

    await service.fetchOnce();
    expect(events).toHaveLength(1);
  });

  it("only emits the highest threshold a bucket has crossed", async () => {
    const events: unknown[] = [];
    const gateway = mockGateway(makeUsage({ burstPercent: 95 }));
    service = makeService(gateway, makeActivityMonitor());
    service.on(UsageMonitorEvent.ThresholdCrossed, (e) => events.push(e));

    await service.fetchOnce();
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ threshold: 90 });
  });

  it("doesn't re-emit after a relaunch with persisted dedupe", async () => {
    const events: unknown[] = [];
    const gateway = mockGateway(makeUsage({ burstPercent: 55 }));
    service = makeService(gateway, makeActivityMonitor());
    service.on(UsageMonitorEvent.ThresholdCrossed, (e) => events.push(e));
    await service.fetchOnce();
    expect(events).toHaveLength(1);
    service.stop();

    service = makeService(gateway, makeActivityMonitor());
    service.on(UsageMonitorEvent.ThresholdCrossed, (e) => events.push(e));
    await service.fetchOnce();
    expect(events).toHaveLength(1);
  });

  it("tracks burst and sustained as independent buckets", async () => {
    const events: unknown[] = [];
    const gateway = mockGateway(
      makeUsage({
        burstPercent: 55,
        sustainedPercent: 80,
        billingPeriodEnd: "2026-06-01T00:00:00.000Z",
      }),
    );
    service = makeService(gateway, makeActivityMonitor());
    service.on(UsageMonitorEvent.ThresholdCrossed, (e) => events.push(e));

    await service.fetchOnce();
    expect(events).toHaveLength(2);
    expect(events.map((e) => (e as { bucket: string }).bucket).sort()).toEqual([
      "burst",
      "sustained",
    ]);
  });

  it("marks events with isPro from the gateway", async () => {
    const events: { isPro: boolean }[] = [];
    const gateway = mockGateway(
      makeUsage({
        sustainedPercent: 60,
        isPro: true,
        billingPeriodEnd: "2026-06-01T00:00:00.000Z",
      }),
    );
    service = makeService(gateway, makeActivityMonitor());
    service.on(UsageMonitorEvent.ThresholdCrossed, (e) =>
      events.push(e as { isPro: boolean }),
    );

    await service.fetchOnce();
    expect(events[0]?.isPro).toBe(true);
  });

  it("marks events with userIsActive from the agent service", async () => {
    const events: { userIsActive: boolean }[] = [];
    const gateway = mockGateway(makeUsage({ burstPercent: 78 }));
    service = makeService(
      gateway,
      makeActivityMonitor({ hasActiveSessions: true }),
    );
    service.on(UsageMonitorEvent.ThresholdCrossed, (e) =>
      events.push(e as { userIsActive: boolean }),
    );

    await service.fetchOnce();
    expect(events[0]?.userIsActive).toBe(true);
  });

  it("backs off after a failure instead of refetching on the next trigger", async () => {
    const fetchUsage = vi.fn().mockRejectedValue(new Error("HTTP 401"));
    const gateway = { fetchUsage } as unknown as GatewaySlice;
    service = makeService(gateway, makeActivityMonitor());

    await service.fetchOnce();
    await service.fetchOnce();
    expect(fetchUsage).toHaveBeenCalledTimes(1);

    // The first window is the 5s base, jittered down to at most 5s.
    vi.advanceTimersByTime(5_001);
    await service.fetchOnce();
    expect(fetchUsage).toHaveBeenCalledTimes(2);
  });

  it("keeps backing off when a mid-failure refresh emits a state change", async () => {
    const fetchUsage = vi.fn().mockRejectedValue(new Error("HTTP 401"));
    const gateway = { fetchUsage } as unknown as GatewaySlice;
    service = makeService(gateway, makeActivityMonitor());

    await service.fetchOnce();
    // The 401 retry refreshes the token from inside the failing fetch.
    // Releasing the window on that emission pins it at its floor.
    emitAuthState("org-1", "authenticated");
    await service.fetchOnce();
    expect(fetchUsage).toHaveBeenCalledTimes(1);
  });

  it("grows the backoff window and caps it at the backstop interval", async () => {
    vi.spyOn(Math, "random").mockReturnValue(0);
    const fetchUsage = vi.fn().mockRejectedValue(new Error("HTTP 500"));
    const gateway = { fetchUsage } as unknown as GatewaySlice;
    service = makeService(gateway, makeActivityMonitor());

    // Jitter pinned at its low end, so windows are 2.5s, 5s, 10s, ... 15m.
    await service.fetchOnce();
    vi.advanceTimersByTime(2_500);
    await service.fetchOnce();
    expect(fetchUsage).toHaveBeenCalledTimes(2);

    // A flat, non-doubling backoff would release here.
    vi.advanceTimersByTime(2_500);
    await service.fetchOnce();
    expect(fetchUsage).toHaveBeenCalledTimes(2);
    vi.advanceTimersByTime(2_500);
    await service.fetchOnce();
    expect(fetchUsage).toHaveBeenCalledTimes(3);

    for (let i = 0; i < 12; i++) {
      vi.advanceTimersByTime(15 * 60_000);
      await service.fetchOnce();
    }
    const capped = fetchUsage.mock.calls.length;
    vi.advanceTimersByTime(15 * 60_000 - 1);
    await service.fetchOnce();
    expect(fetchUsage).toHaveBeenCalledTimes(capped);
    vi.advanceTimersByTime(1);
    await service.fetchOnce();
    expect(fetchUsage).toHaveBeenCalledTimes(capped + 1);
  });

  it("stops polling entirely after a terminal auth failure", async () => {
    const fetchUsage = vi.fn().mockRejectedValue(new NotAuthenticatedError());
    const gateway = { fetchUsage } as unknown as GatewaySlice;
    service = makeService(gateway, makeActivityMonitor());
    emitAuthState("org-1", "anonymous");

    await service.fetchOnce();
    // No window expiry releases this one, and a signed-out session must not.
    vi.advanceTimersByTime(6 * 60 * 60_000);
    await service.fetchOnce();
    expect(fetchUsage).toHaveBeenCalledTimes(1);

    emitAuthState("org-1", "authenticated");
    await service.fetchOnce();
    expect(fetchUsage).toHaveBeenCalledTimes(2);
  });

  it("recovers polling when the user signs back into the same organization", async () => {
    const fetchUsage = vi.fn().mockRejectedValue(new NotAuthenticatedError());
    const gateway = { fetchUsage } as unknown as GatewaySlice;
    service = makeService(gateway, makeActivityMonitor());
    emitAuthState("org-1", "anonymous");

    await service.fetchOnce();
    expect(fetchUsage).toHaveBeenCalledTimes(1);

    // A teardown publishes the anonymous org before any new sign-in, so
    // returning to the same org is still a transition the listener acts on.
    emitAuthState(null, "anonymous");
    fetchUsage.mockResolvedValue(makeUsage());
    emitAuthState("org-1", "authenticated");
    await vi.advanceTimersByTimeAsync(10_000);

    expect(fetchUsage).toHaveBeenCalledTimes(2);
  });

  it("resets the window after a success", async () => {
    vi.spyOn(Math, "random").mockReturnValue(0);
    const fetchUsage = vi
      .fn()
      .mockRejectedValueOnce(new Error("HTTP 500"))
      .mockRejectedValueOnce(new Error("HTTP 500"))
      .mockResolvedValueOnce(makeUsage({ burstPercent: 10 }))
      .mockRejectedValue(new Error("HTTP 500"));
    const gateway = { fetchUsage } as unknown as GatewaySlice;
    service = makeService(gateway, makeActivityMonitor());

    await service.fetchOnce();
    vi.advanceTimersByTime(2_500);
    await service.fetchOnce();
    vi.advanceTimersByTime(5_000);
    await service.fetchOnce();
    expect(fetchUsage).toHaveBeenCalledTimes(3);

    // The next failure starts from the base, not the escalated window.
    await service.fetchOnce();
    vi.advanceTimersByTime(2_500);
    await service.fetchOnce();
    expect(fetchUsage).toHaveBeenCalledTimes(5);
  });

  it("lets an org switch refetch through an open backoff window", async () => {
    vi.spyOn(Math, "random").mockReturnValue(0);
    const fetchUsage = vi.fn().mockRejectedValue(new Error("HTTP 500"));
    const gateway = { fetchUsage } as unknown as GatewaySlice;
    service = makeService(gateway, makeActivityMonitor());

    // Three failures put the window at 10s, wider than the coalesce delay the
    // switch's refetch waits out, so the window is still open when it fires.
    await service.fetchOnce();
    vi.advanceTimersByTime(2_500);
    await service.fetchOnce();
    vi.advanceTimersByTime(5_000);
    await service.fetchOnce();
    expect(fetchUsage).toHaveBeenCalledTimes(3);

    // The switch drops the snapshot, so its refetch must not be swallowed.
    emitAuthState("org-2");
    await vi.advanceTimersByTimeAsync(5_001);
    expect(fetchUsage).toHaveBeenCalledTimes(4);
  });

  it("lets a forced refresh skip the timed window", async () => {
    const fetchUsage = vi.fn().mockRejectedValue(new Error("HTTP 500"));
    const gateway = { fetchUsage } as unknown as GatewaySlice;
    service = makeService(gateway, makeActivityMonitor());

    await service.fetchOnce();
    await service.fetchOnce();
    expect(fetchUsage).toHaveBeenCalledTimes(1);

    await service.refreshNow();
    expect(fetchUsage).toHaveBeenCalledTimes(2);
  });

  it("does not let a forced refresh bypass the terminal stop", async () => {
    const fetchUsage = vi.fn().mockRejectedValue(new NotAuthenticatedError());
    const gateway = { fetchUsage } as unknown as GatewaySlice;
    service = makeService(gateway, makeActivityMonitor());
    emitAuthState("org-1", "anonymous");

    await service.fetchOnce();
    // A forced fetch with no session cannot succeed.
    await service.refreshNow();
    expect(fetchUsage).toHaveBeenCalledTimes(1);
  });

  it("warns when it enters the terminal stop", async () => {
    const fetchUsage = vi.fn().mockRejectedValue(new NotAuthenticatedError());
    const gateway = { fetchUsage } as unknown as GatewaySlice;
    service = makeService(gateway, makeActivityMonitor());

    await service.fetchOnce();

    expect(lastScopedLog.warn).toHaveBeenCalledWith(
      expect.stringContaining("re-auth"),
      { reason: "reauth_required" },
    );
  });

  it("silently skips polls when the gateway throws", async () => {
    const events: unknown[] = [];
    const gateway = {
      fetchUsage: vi.fn().mockRejectedValue(new Error("not authenticated")),
    } as unknown as GatewaySlice;
    service = makeService(gateway, makeActivityMonitor());
    service.on(UsageMonitorEvent.ThresholdCrossed, (e) => events.push(e));

    await expect(service.fetchOnce()).resolves.toBeNull();
    expect(events).toHaveLength(0);
  });

  it("emits UsageUpdated only when the snapshot actually changes", async () => {
    const updates: UsageOutput[] = [];
    const gateway = {
      fetchUsage: vi
        .fn()
        .mockResolvedValueOnce(makeUsage({ burstPercent: 20 }))
        .mockResolvedValueOnce(makeUsage({ burstPercent: 20 }))
        .mockResolvedValueOnce(makeUsage({ burstPercent: 35 })),
    } as unknown as GatewaySlice;
    service = makeService(gateway, makeActivityMonitor());
    service.on(UsageMonitorEvent.UsageUpdated, (u) => updates.push(u));

    expect(service.getLatest()).toBeNull();
    await service.fetchOnce();
    expect(updates).toHaveLength(1);
    expect(service.getLatest()?.burst.used_percent).toBe(20);

    await service.fetchOnce();
    expect(updates).toHaveLength(1);

    await service.fetchOnce();
    expect(updates).toHaveLength(2);
    expect(updates[1].burst.used_percent).toBe(35);
  });

  it.each([
    ["subscribed", true],
    ["unknown", undefined],
  ] as const)(
    "does not emit thresholds for a %s org's internal valves",
    async (_name, subscribed) => {
      const usage = {
        ...makeUsage({ sustainedPercent: 90 }),
        code_usage_subscribed: subscribed,
      };
      service = makeService(mockGateway(usage), makeActivityMonitor());
      const thresholds: unknown[] = [];
      const updates: unknown[] = [];
      service.on(UsageMonitorEvent.ThresholdCrossed, (e) => thresholds.push(e));
      service.on(UsageMonitorEvent.UsageUpdated, (u) => updates.push(u));

      await service.fetchOnce();

      expect(thresholds).toHaveLength(0);
      // The snapshot still flows to the meters.
      expect(updates).toHaveLength(1);
    },
  );

  // The titlebar meter keys off this bit; a subscribe flip must not wait for
  // some other field to change.
  it("emits UsageUpdated when only the org spend numbers change", async () => {
    const updates: UsageOutput[] = [];
    const gateway = {
      fetchUsage: vi
        .fn()
        .mockResolvedValueOnce({
          ...makeUsage(),
          ai_credits: { exhausted: false, used_usd: 12.4, limit_usd: 50 },
        })
        .mockResolvedValueOnce({
          ...makeUsage(),
          ai_credits: { exhausted: false, used_usd: 13.1, limit_usd: 50 },
        }),
    } as unknown as GatewaySlice;
    service = makeService(gateway, makeActivityMonitor());
    service.on(UsageMonitorEvent.UsageUpdated, (u) => updates.push(u));

    await service.fetchOnce();
    await service.fetchOnce();

    expect(updates).toHaveLength(2);
    expect(updates[1].ai_credits?.used_usd).toBe(13.1);
  });

  it("forgets the snapshot and refetches when the organization changes", async () => {
    const gateway = mockGateway(makeUsage());
    service = makeService(gateway, makeActivityMonitor());
    await service.fetchOnce();
    expect(service.getLatest()).not.toBeNull();

    emitAuthState("org-2");

    expect(service.getLatest()).toBeNull();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(gateway.fetchUsage).toHaveBeenCalledTimes(2);
    expect(service.getLatest()).not.toBeNull();
  });

  it("keeps the snapshot across same-org auth changes", async () => {
    service = makeService(mockGateway(makeUsage()), makeActivityMonitor());
    await service.fetchOnce();

    emitAuthState("org-1");

    expect(service.getLatest()).not.toBeNull();
  });

  it("clears the snapshot on sign-out without scheduling a refetch", async () => {
    const gateway = mockGateway(makeUsage());
    service = makeService(gateway, makeActivityMonitor());
    await service.fetchOnce();

    emitAuthState(null);

    expect(service.getLatest()).toBeNull();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(gateway.fetchUsage).toHaveBeenCalledTimes(1);
  });

  it("emits UsageUpdated when only the subscription bit flips", async () => {
    const updates: UsageOutput[] = [];
    const gateway = {
      fetchUsage: vi
        .fn()
        .mockResolvedValueOnce({
          ...makeUsage(),
          code_usage_subscribed: false,
        })
        .mockResolvedValueOnce({ ...makeUsage(), code_usage_subscribed: true }),
    } as unknown as GatewaySlice;
    service = makeService(gateway, makeActivityMonitor());
    service.on(UsageMonitorEvent.UsageUpdated, (u) => updates.push(u));

    await service.fetchOnce();
    await service.fetchOnce();

    expect(updates).toHaveLength(2);
    expect(updates[1].code_usage_subscribed).toBe(true);
  });

  it("does not emit UsageUpdated when the gateway throws", async () => {
    const updates: UsageOutput[] = [];
    const gateway = {
      fetchUsage: vi.fn().mockRejectedValue(new Error("offline")),
    } as unknown as GatewaySlice;
    service = makeService(gateway, makeActivityMonitor());
    service.on(UsageMonitorEvent.UsageUpdated, (u) => updates.push(u));

    await service.fetchOnce();
    expect(updates).toHaveLength(0);
    expect(service.getLatest()).toBeNull();
  });

  it("refreshNow triggers a fresh fetch and returns the snapshot", async () => {
    const gateway = mockGateway(makeUsage({ burstPercent: 42 }));
    service = makeService(gateway, makeActivityMonitor());

    const result = await service.refreshNow();
    expect(result?.burst.used_percent).toBe(42);
    expect(service.getLatest()?.burst.used_percent).toBe(42);
  });

  it("collapses bursts of LlmActivity into at most one trailing fetch", async () => {
    const gateway = mockGateway(makeUsage({ burstPercent: 10 }));
    const agent = makeActivityMonitor();
    service = makeService(gateway, agent);
    service.init();
    await vi.advanceTimersByTimeAsync(0);
    expect(gateway.fetchUsage).toHaveBeenCalledTimes(1);

    agent.fireLlmActivity();
    agent.fireLlmActivity();
    agent.fireLlmActivity();
    agent.fireLlmActivity();
    await vi.advanceTimersByTimeAsync(0);
    expect(gateway.fetchUsage).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(5_000);
    expect(gateway.fetchUsage).toHaveBeenCalledTimes(2);

    await vi.advanceTimersByTimeAsync(60_000);
    agent.fireLlmActivity();
    await vi.advanceTimersByTimeAsync(5_000);
    expect(gateway.fetchUsage).toHaveBeenCalledTimes(3);
  });

  it("unsubscribes from agent events on stop()", async () => {
    const gateway = mockGateway(makeUsage({ burstPercent: 10 }));
    const agent = makeActivityMonitor();
    service = makeService(gateway, agent);
    service.init();
    await vi.advanceTimersByTimeAsync(0);
    const baseline = (gateway.fetchUsage as ReturnType<typeof vi.fn>).mock.calls
      .length;

    service.stop();
    agent.fireLlmActivity();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(gateway.fetchUsage).toHaveBeenCalledTimes(baseline);
  });
});
