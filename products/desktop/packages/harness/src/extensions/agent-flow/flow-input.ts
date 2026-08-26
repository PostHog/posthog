/**
 * Routes user input to a running flow. During a flow the main session looks
 * busy, so clients send steer/follow-up commands instead of prompts; the rpc
 * host asks this router first before the main agent's queue takes them.
 * Steer goes to the running step; follow-up becomes guidance for the next
 * step.
 */

export type FlowInputMode = "steer" | "followUp";
type FlowInputRouter = (text: string, mode: FlowInputMode) => boolean;

// tsup inlines this module separately into every bundle that imports it, so
// module-level state would split into per-bundle copies. The global-registry
// symbol keys one shared slot across all copies in the process.
const GLOBAL_KEY = Symbol.for("posthog.agent-flow.input-router");
const globalStore = globalThis as {
  [GLOBAL_KEY]?: { router: FlowInputRouter | null };
};
globalStore[GLOBAL_KEY] ??= { router: null };
const slot = globalStore[GLOBAL_KEY];

export function setFlowInputRouter(router: FlowInputRouter | null): void {
  slot.router = router;
}

/** True when a flow consumed the input. */
export function tryRouteFlowInput(text: string, mode: FlowInputMode): boolean {
  if (!slot.router || !text.trim() || text.trim().startsWith("/")) {
    return false;
  }
  return slot.router(text.trim(), mode);
}
