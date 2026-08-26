/**
 * In-process fan-out for live flow step events. The extension emits them from
 * each step's in-process session; the rpc host injects them into the parent
 * session's outgoing event stream so any client can render the step's work.
 */
import type { AgentFlowStepStreamEvent } from "@posthog/shared";

type FlowStepEventListener = (event: AgentFlowStepStreamEvent) => void;

// tsup inlines this module separately into every bundle that imports it, so
// module-level state would split into per-bundle copies. The global-registry
// symbol keys one shared listener set across all copies in the process.
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
