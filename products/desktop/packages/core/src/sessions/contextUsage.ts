import type { AcpMessage } from "@posthog/shared";
import { createAppendOnlyTracker } from "./appendOnlyTracker";

export interface ContextBreakdown {
  systemPrompt: number;
  tools: number;
  rules: number;
  skills: number;
  mcp: number;
  subagents: number;
  conversation: number;
}

export interface ContextUsage {
  used: number;
  size: number;
  percentage: number;
  /** Cumulative estimated session cost, summed across turns; `null` if none reported (e.g. codex). */
  cost: { amount: number; currency: string } | null;
  breakdown: ContextBreakdown | null;
}

type ContextUsageAggregate = Omit<ContextUsage, "breakdown" | "cost">;

export function extractContextUsage(events: AcpMessage[]): ContextUsage | null {
  let aggregate: ContextUsageAggregate | null = null;
  let breakdown: ContextBreakdown | null = null;
  let costAmount: number | null = null;
  let costCurrency = "USD";

  // Cost sums over every turn, so this can't early-break once the newest
  // aggregate/breakdown is found — it walks the full log.
  for (let i = events.length - 1; i >= 0; i--) {
    const msg = events[i].message;
    const cost = extractCost(msg);
    if (cost) {
      costAmount = (costAmount ?? 0) + cost.amount;
      costCurrency = cost.currency;
    }
    if (!aggregate) {
      aggregate = extractAggregate(msg);
    } else if (aggregate.size <= 0) {
      // The newest update omitted the context window; borrow it from an older one.
      const older = extractAggregate(msg);
      if (older) aggregate = withCarriedSize(aggregate, older);
    }
    if (!breakdown) {
      breakdown = extractBreakdown(msg);
    }
  }

  if (!aggregate) return null;
  return { ...aggregate, cost: toCost(costAmount, costCurrency), breakdown };
}

interface ContextUsageState {
  aggregate: ContextUsageAggregate | null;
  costAmount: number | null;
  costCurrency: string;
  breakdown: ContextBreakdown | null;
}

export function createContextUsageTracker() {
  return createAppendOnlyTracker<ContextUsageState, ContextUsage | null>({
    init: () => ({
      aggregate: null,
      costAmount: null,
      costCurrency: "USD",
      breakdown: null,
    }),
    processEvent: (state, event) => {
      const msg = event.message;
      const next = extractAggregate(msg);
      if (next) {
        state.aggregate = withCarriedSize(next, state.aggregate);
      }
      const cost = extractCost(msg);
      if (cost) {
        state.costAmount = (state.costAmount ?? 0) + cost.amount;
        state.costCurrency = cost.currency;
      }
      state.breakdown = extractBreakdown(msg) ?? state.breakdown;
    },
    getResult: (state) =>
      state.aggregate
        ? {
            ...state.aggregate,
            cost: toCost(state.costAmount, state.costCurrency),
            breakdown: state.breakdown,
          }
        : null,
  });
}

function toCost(amount: number | null, currency: string): ContextUsage["cost"] {
  return amount != null ? { amount, currency } : null;
}

/**
 * An update that omits `size` must not wipe a previously known context window
 * (codex reports `modelContextWindow` intermittently), so keep the last known
 * size and recompute the percentage against it.
 */
function withCarriedSize(
  next: ContextUsageAggregate,
  previous: ContextUsageAggregate | null,
): ContextUsageAggregate {
  if (next.size > 0 || !previous || previous.size <= 0) return next;
  const size = previous.size;
  return {
    ...next,
    size,
    percentage: Math.min(100, Math.round((next.used / size) * 100)),
  };
}

function extractAggregate(
  msg: AcpMessage["message"],
): ContextUsageAggregate | null {
  if (
    "method" in msg &&
    msg.method === "session/update" &&
    !("id" in msg) &&
    "params" in msg
  ) {
    const params = msg.params as
      | {
          update?: {
            sessionUpdate?: string;
            used?: number;
            size?: number;
            cost?: { amount: number; currency: string } | null;
          };
        }
      | undefined;
    const update = params?.update;
    if (
      update?.sessionUpdate === "usage_update" &&
      typeof update.used === "number"
    ) {
      // The model context window (`size`) may be unknown — e.g. codex omits it
      // when the protocol doesn't report `modelContextWindow`. Still surface the
      // raw token count (size 0 → the indicator shows used tokens, no
      // percentage) rather than dropping the whole aggregate.
      const size = typeof update.size === "number" ? update.size : 0;
      const percentage =
        size > 0 ? Math.min(100, Math.round((update.used / size) * 100)) : 0;
      return { used: update.used, size, percentage };
    }
  }
  return null;
}

function extractCost(
  msg: AcpMessage["message"],
): { amount: number; currency: string } | null {
  if (
    "method" in msg &&
    msg.method === "session/update" &&
    !("id" in msg) &&
    "params" in msg
  ) {
    const params = msg.params as
      | {
          update?: {
            sessionUpdate?: string;
            cost?: { amount: number; currency: string } | null;
          };
        }
      | undefined;
    const update = params?.update;
    if (
      update?.sessionUpdate === "usage_update" &&
      update.cost &&
      typeof update.cost.amount === "number"
    ) {
      return {
        amount: update.cost.amount,
        currency: update.cost.currency ?? "USD",
      };
    }
  }
  return null;
}

function extractBreakdown(msg: AcpMessage["message"]): ContextBreakdown | null {
  if (!("method" in msg) || !("params" in msg)) return null;
  if (
    msg.method !== "_posthog/usage_update" &&
    msg.method !== "__posthog/usage_update"
  ) {
    return null;
  }
  const params = msg.params as { breakdown?: ContextBreakdown } | undefined;
  return params?.breakdown ?? null;
}
