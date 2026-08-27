import type { AgentFlowStepStreamEvent } from "@posthog/shared";

type FlowStepEventListener = (event: AgentFlowStepStreamEvent) => void;

// tsup inlines this module per bundle; the global symbol keys one shared slot.
const GLOBAL_KEY = Symbol.for("posthog.agent-flow.step-event-listeners");
const globalStore = globalThis as {
  [GLOBAL_KEY]?: Set<FlowStepEventListener>;
};
globalStore[GLOBAL_KEY] ??= new Set();
const listeners: Set<FlowStepEventListener> = globalStore[GLOBAL_KEY];

export function onFlowStepEvent(listener: FlowStepEventListener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function emitFlowStepEvent(event: AgentFlowStepStreamEvent): void {
  for (const listener of listeners) {
    listener(event);
  }
}
