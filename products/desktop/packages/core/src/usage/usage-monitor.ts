import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import { TypedEventEmitter } from "@posthog/shared";
import { inject, injectable, postConstruct, preDestroy } from "inversify";
import type { AuthService } from "../auth/auth";
import { AUTH_SERVICE } from "../auth/auth.module";
import { AuthServiceEvent } from "../auth/schemas";
import { isCodeUsageFreeTier } from "../billing/usageDisplay";
import { USAGE_HOST, type UsageHost, type UsageLogger } from "./identifiers";
import {
  USAGE_THRESHOLDS,
  UsageMonitorEvent,
  type UsageMonitorEvents,
  type UsageThreshold,
} from "./monitor-schemas";
import type { UsageBucket, UsageOutput } from "./schemas";

const COALESCE_INTERVAL_MS = 5_000;
// Catches reset-window rollovers and out-of-band plan changes while the app
// sits idle and no LlmActivity events fire.
const BACKSTOP_INTERVAL_MS = 30 * 60_000;

type BucketName = "burst" | "sustained";

@injectable()
export class UsageMonitorService extends TypedEventEmitter<UsageMonitorEvents> {
  private backstopTimeoutId: ReturnType<typeof setTimeout> | null = null;
  private coalesceTimeoutId: ReturnType<typeof setTimeout> | null = null;
  private lastFetchStartedAt = 0;
  private isFetching = false;
  private thresholdsSeen: Record<string, string>;
  private latestUsage: UsageOutput | null = null;

  private readonly onLlmActivity = (): void => this.requestRefresh();

  constructor(
    @inject(USAGE_HOST)
    private readonly host: UsageHost,
    @inject(ROOT_LOGGER)
    logger: RootLogger,
    @inject(AUTH_SERVICE)
    authService: AuthService,
  ) {
    super();
    this.log = logger.scope("usage-monitor");
    this.thresholdsSeen = { ...this.host.getThresholdsSeen() };
    // The snapshot is identity-scoped billing data: a signed-in account must
    // never be served the previous account's spend.
    let orgId = authService.getState().currentOrgId;
    authService.on(AuthServiceEvent.StateChanged, (state) => {
      if (state.currentOrgId === orgId) return;
      orgId = state.currentOrgId;
      this.latestUsage = null;
      if (state.currentOrgId !== null) this.requestRefresh();
    });
  }

  private readonly log: UsageLogger;

  getLatest(): UsageOutput | null {
    return this.latestUsage;
  }

  async refreshNow(): Promise<UsageOutput | null> {
    return this.fetchOnce();
  }

  // Coalesces N parallel agents finishing turns into at most two fetches
  // (leading + trailing) per `COALESCE_INTERVAL_MS` window.
  requestRefresh(): void {
    if (this.coalesceTimeoutId) return;
    const now = Date.now();
    const delay = Math.max(
      0,
      this.lastFetchStartedAt + COALESCE_INTERVAL_MS - now,
    );
    this.coalesceTimeoutId = setTimeout(() => {
      this.coalesceTimeoutId = null;
      void this.fetchOnce();
    }, delay);
  }

  @postConstruct()
  init(): void {
    this.pruneStaleEntries();
    this.host.onLlmActivity(this.onLlmActivity);
    void this.fetchOnce();
    this.scheduleBackstop();
  }

  @preDestroy()
  stop(): void {
    this.host.offLlmActivity(this.onLlmActivity);
    if (this.backstopTimeoutId) {
      clearTimeout(this.backstopTimeoutId);
      this.backstopTimeoutId = null;
    }
    if (this.coalesceTimeoutId) {
      clearTimeout(this.coalesceTimeoutId);
      this.coalesceTimeoutId = null;
    }
  }

  async fetchOnce(): Promise<UsageOutput | null> {
    if (this.isFetching) return null;
    this.isFetching = true;
    this.lastFetchStartedAt = Date.now();
    if (this.coalesceTimeoutId) {
      clearTimeout(this.coalesceTimeoutId);
      this.coalesceTimeoutId = null;
    }
    try {
      let usage: UsageOutput | null = null;
      try {
        usage = await this.host.fetchUsage();
      } catch (err) {
        this.log.debug("Usage fetch skipped", {
          error: err instanceof Error ? err.message : String(err),
        });
      }
      if (usage) {
        const changed = !isSameUsage(this.latestUsage, usage);
        this.latestUsage = usage;
        if (changed) {
          this.emit(UsageMonitorEvent.UsageUpdated, usage);
        }
        this.processUsage(usage);
      }
      return usage;
    } finally {
      this.isFetching = false;
    }
  }

  private scheduleBackstop(): void {
    this.backstopTimeoutId = setTimeout(async () => {
      this.backstopTimeoutId = null;
      await this.fetchOnce();
      this.scheduleBackstop();
    }, BACKSTOP_INTERVAL_MS);
  }

  private processUsage(usage: UsageOutput): void {
    // Valve thresholds are a free-tier concept — a subscribed org's valves
    // are internal rails, and unknown must never read as free.
    if (!isCodeUsageFreeTier(usage)) return;
    const userId = usage.user_id.toString();
    const product = usage.product;
    this.maybeEmit(usage, "burst", usage.burst, userId, product, usage.is_pro);
    this.maybeEmit(
      usage,
      "sustained",
      usage.sustained,
      userId,
      product,
      usage.is_pro,
    );
  }

  private maybeEmit(
    usage: UsageOutput,
    bucket: BucketName,
    status: UsageBucket,
    userId: string,
    product: string,
    isPro: boolean,
  ): void {
    const anchor = this.anchorFor(bucket, status, usage);
    if (!anchor) return;

    const threshold = highestThresholdCrossed(status.used_percent);
    if (threshold === null) return;

    const key = makeKey(userId, product, bucket, anchor, threshold);
    if (this.thresholdsSeen[key]) return;

    this.thresholdsSeen[key] = anchor;
    this.host.setThresholdsSeen(this.thresholdsSeen);

    this.log.info("Usage threshold crossed", {
      bucket,
      threshold,
      usedPercent: status.used_percent,
    });

    this.emit(UsageMonitorEvent.ThresholdCrossed, {
      bucket,
      threshold,
      usedPercent: status.used_percent,
      resetAt: status.reset_at,
      isPro,
      userIsActive: this.host.hasActiveSessions(),
    });
  }

  // Rounded anchor so transient TTL jitter doesn't make every poll look like
  // a fresh window.
  private anchorFor(
    bucket: BucketName,
    status: UsageBucket,
    usage: UsageOutput,
  ): string | null {
    if (bucket === "sustained") {
      return usage.billing_period_end ?? sustainedFreeAnchor(status) ?? null;
    }
    return burstAnchor(status);
  }

  private pruneStaleEntries(): void {
    const now = Date.now();
    let dirty = false;
    for (const [key, anchor] of Object.entries(this.thresholdsSeen)) {
      const parsed = Date.parse(anchor);
      if (Number.isNaN(parsed) || parsed < now) {
        delete this.thresholdsSeen[key];
        dirty = true;
      }
    }
    if (dirty) {
      this.host.setThresholdsSeen(this.thresholdsSeen);
    }
  }
}

function highestThresholdCrossed(usedPercent: number): UsageThreshold | null {
  for (let i = USAGE_THRESHOLDS.length - 1; i >= 0; i--) {
    const t = USAGE_THRESHOLDS[i];
    if (usedPercent >= t) return t;
  }
  return null;
}

function burstAnchor(status: UsageBucket): string | null {
  const resetMs = resetMillis(status);
  if (resetMs === null) return null;
  // Round to the nearest hour so 30s polling doesn't churn the anchor.
  const rounded = Math.round(resetMs / 3_600_000) * 3_600_000;
  return new Date(rounded).toISOString();
}

function sustainedFreeAnchor(status: UsageBucket): string | null {
  const resetMs = resetMillis(status);
  if (resetMs === null) return null;
  return new Date(resetMs).toISOString().slice(0, 10);
}

function resetMillis(status: UsageBucket): number | null {
  const parsed = Date.parse(status.reset_at);
  return Number.isNaN(parsed) ? null : parsed;
}

function makeKey(
  userId: string,
  product: string,
  bucket: BucketName,
  anchor: string,
  threshold: UsageThreshold,
): string {
  return `${userId}:${product}:${bucket}:${anchor}:${threshold}`;
}

function isSameUsage(a: UsageOutput | null, b: UsageOutput): boolean {
  if (!a) return false;
  return (
    a.is_rate_limited === b.is_rate_limited &&
    a.billing_period_end === b.billing_period_end &&
    a.code_usage_subscribed === b.code_usage_subscribed &&
    a.ai_credits?.exhausted === b.ai_credits?.exhausted &&
    a.ai_credits?.used_usd === b.ai_credits?.used_usd &&
    a.ai_credits?.limit_usd === b.ai_credits?.limit_usd &&
    isSameBucket(a.burst, b.burst) &&
    isSameBucket(a.sustained, b.sustained)
  );
}

function isSameBucket(a: UsageBucket, b: UsageBucket): boolean {
  return (
    a.used_percent === b.used_percent &&
    a.reset_at === b.reset_at &&
    a.exceeded === b.exceeded
  );
}
