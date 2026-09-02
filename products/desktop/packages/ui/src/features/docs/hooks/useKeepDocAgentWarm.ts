import { useWarmTask } from "@posthog/ui/features/task-detail/hooks/useWarmTask";
import {
  DOC_AGENT_ADAPTER,
  DOC_AGENT_BRANCH,
  DOC_AGENT_EXECUTION_MODE,
  DOC_AGENT_MODEL,
  DOC_AGENT_REASONING_EFFORT,
  DOC_AGENT_RUNTIME,
  DOC_AGENT_WORKSPACE_MODE,
} from "./docAgent";

// Shared, because the warming effect re-arms its debounce whenever this array
// changes identity: a fresh literal per render would postpone the warm forever.
const NO_REPOSITORIES: string[] = [];

/**
 * Keeps one run warm for this page's agent.
 *
 * Asking for data from a page has to feel like the page already knew it, so the
 * sandbox boots while the page is open rather than after the question. The pool
 * reuses an idling run, so a second doc costs nothing, and an abandoned warm is
 * reaped by its own inactivity timeout.
 */
export function useKeepDocAgentWarm(): void {
  // A local run has nothing to warm: it starts in this window. The hook still
  // runs, so the pool is armed the moment the page's agent moves to the cloud.
  useWarmTask({
    workspaceMode: DOC_AGENT_WORKSPACE_MODE,
    runtime: DOC_AGENT_RUNTIME,
    // The pool matches on the mode too, so the warm boots in the mode a page
    // request runs in.
    initialPermissionMode: DOC_AGENT_EXECUTION_MODE,
    allowNoRepo: true,
    repositories: NO_REPOSITORIES,
    branch: DOC_AGENT_BRANCH,
    runtimeAdapter: DOC_AGENT_ADAPTER,
    model: DOC_AGENT_MODEL,
    reasoningEffort: DOC_AGENT_REASONING_EFFORT,
    // The warm exists for the page, not for something typed into a composer, so
    // it is armed as soon as the page is open.
    editorIsEmpty: false,
    // An idle warm is reaped after ten minutes; a page stays open longer than that.
    renewEveryMs: 8 * 60_000,
  });
}
