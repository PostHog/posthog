import type { AcpMessage } from "@posthog/shared";

/**
 * Folds a growing session event log into running state, visiting only the tail
 * appended since the last call so streaming stays O(appended), not O(history).
 *
 * An append is detected by reference identity: the same array again, or a longer
 * one whose first and previous-boundary elements are unchanged. Otherwise the
 * state is rebuilt. A same-length array counts as a replacement even when both
 * ends survive, because the cloud log reconcile swaps a middle segment for
 * hydrated entries while retaining the leading prefix and the live tail, and
 * folding only the tail there would drop the replaced entries for good.
 *
 * `processEvent` mutates `state`; `getResult` projects it, allocating a fresh
 * value so a retained result never sees `state` mutate underneath it.
 */
export function createAppendOnlyTracker<State, Result>(config: {
  init: () => State;
  processEvent: (state: State, event: AcpMessage) => void;
  getResult: (state: State) => Result;
}) {
  let state = config.init();
  let processedCount = 0;
  let eventsRef: AcpMessage[] | null = null;
  let firstEventRef: AcpMessage | null = null;
  let boundaryEventRef: AcpMessage | null = null;

  const update = (events: AcpMessage[]): Result => {
    const isAppend =
      processedCount === 0 ||
      (events === eventsRef && events.length === processedCount) ||
      (events.length > processedCount &&
        events[0] === firstEventRef &&
        events[processedCount - 1] === boundaryEventRef);

    if (!isAppend) {
      state = config.init();
      processedCount = 0;
    }

    for (let i = processedCount; i < events.length; i++) {
      config.processEvent(state, events[i]);
    }

    processedCount = events.length;
    eventsRef = events;
    firstEventRef = events[0] ?? null;
    boundaryEventRef = events[processedCount - 1] ?? null;

    return config.getResult(state);
  };

  return { update };
}
