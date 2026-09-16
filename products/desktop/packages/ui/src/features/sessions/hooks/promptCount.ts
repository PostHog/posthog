import { createAppendOnlyTracker } from "@posthog/core/sessions/appendOnlyTracker";
import { extractUserPromptsFromEvents } from "@posthog/core/sessions/sessionEvents";
import type { AcpMessage } from "@posthog/shared";

function createPromptCountTracker() {
  return createAppendOnlyTracker<{ count: number }, number>({
    init: () => ({ count: 0 }),
    processEvent: (state, event) => {
      state.count += extractUserPromptsFromEvents([event]).length;
    },
    getResult: (state) => state.count,
  });
}

// Weak keys let eviction release a transcript and its derived count together.
const trackers = new WeakMap<
  AcpMessage,
  ReturnType<typeof createPromptCountTracker>
>();

/**
 * Counts the user prompts in a transcript, folded incrementally so a streaming
 * session costs O(appended) per store write rather than a walk of every event.
 */
export function countUserPrompts(events: AcpMessage[] | undefined): number {
  const first = events?.[0];
  if (!first || !events) return 0;
  let tracker = trackers.get(first);
  if (!tracker) {
    tracker = createPromptCountTracker();
    trackers.set(first, tracker);
  }
  return tracker.update(events);
}
