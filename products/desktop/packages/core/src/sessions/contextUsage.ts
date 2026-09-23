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
  breakdown: ContextBreakdown | null;
  breakdownAvailable?: boolean;
}

type ContextUsageAggregate = Omit<ContextUsage, "breakdown">;

export function extractContextUsage(events: AcpMessage[]): ContextUsage | null {
  let aggregate: ContextUsageAggregate | null = null;
  let breakdown: ContextBreakdown | null = null;

  for (let i = events.length - 1; i >= 0; i--) {
    const msg = events[i].message;
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
  return { ...aggregate, breakdown };
}

interface ContextUsageState {
  aggregate: ContextUsageAggregate | null;
  breakdown: ContextBreakdown | null;
}

export function createContextUsageTracker() {
  return createAppendOnlyTracker<ContextUsageState, ContextUsage | null>({
    init: () => ({
      aggregate: null,
      breakdown: null,
    }),
    processEvent: (state, event) => {
      const msg = event.message;
      const next = extractAggregate(msg);
      if (next) {
        state.aggregate = withCarriedSize(next, state.aggregate);
      }
      state.breakdown = extractBreakdown(msg) ?? state.breakdown;
    },
    getResult: (state) =>
      state.aggregate
        ? {
            ...state.aggregate,
            breakdown: state.breakdown,
          }
        : null,
  });
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
