export type FlowInputMode = "steer" | "followUp";
type FlowInputRouter = (text: string, mode: FlowInputMode) => boolean;

// tsup inlines this module per bundle; the global symbol keys one shared slot.
const GLOBAL_KEY = Symbol.for("posthog.agent-flow.input-router");
const globalStore = globalThis as {
  [GLOBAL_KEY]?: { router: FlowInputRouter | null };
};
globalStore[GLOBAL_KEY] ??= { router: null };
const slot = globalStore[GLOBAL_KEY];

export function setFlowInputRouter(router: FlowInputRouter | null): void {
  slot.router = router;
}

export function tryRouteFlowInput(text: string, mode: FlowInputMode): boolean {
  if (!slot.router || !text.trim() || text.trim().startsWith("/")) {
    return false;
  }
  return slot.router(text.trim(), mode);
}
