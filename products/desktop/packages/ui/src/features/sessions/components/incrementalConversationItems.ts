import type { AcpMessage } from "@posthog/shared";
import {
  type BuildConversationOptions,
  type BuildResult,
  buildConversationItems,
  type ConversationItem,
  createItemBuilder,
  finalizeBuilder,
  type ItemBuilder,
  markThoughtCompletion,
  markTurnContextChanged,
  orderEventsByTimestamp,
  processEvent,
  readLastTurnInfo,
  readTurnContextRevision,
  type TurnContext,
} from "./buildConversationItems";

/**
 * Whether feeding `events[from..]` to the builder keeps the sequence it has
 * already consumed in ascending timestamp order. `lastTs` is the timestamp of
 * the last event fed, so a late arrival that belongs earlier in the transcript
 * fails here and forces a re-read of the whole array in sorted order.
 */
function extendsTimestampOrder(
  events: AcpMessage[],
  from: number,
  lastTs: number,
): boolean {
  let previous = lastTs;
  for (let i = from; i < events.length; i++) {
    if (events[i].ts < previous) return false;
    previous = events[i].ts;
  }
  return true;
}

/**
 * Incremental front end for `buildConversationItems`.
 *
 * A full rebuild re-parses every event on every streamed token — O(n) per
 * token, O(n^2) per turn. This processes each event exactly once into a
 * persistent builder and, on every call, freezes completed turns (their item
 * objects keep identity, so memoized rows skip re-render) while re-deriving
 * only the active turn. Per call the cost is proportional to the active turn,
 * not the whole thread.
 *
 * Output is content-equivalent to `buildConversationItems` for every prefix of
 * events — see incrementalConversationItems.test.ts. It falls back to a full
 * rebuild whenever the append-only fast path can't faithfully represent the
 * state (idle, non-append event change, options change, or a progress card in
 * an already-frozen turn being mutated).
 */
export function createIncrementalConversationBuilder() {
  let b: ItemBuilder | null = null;
  let processedCount = 0;
  let firstEventRef: AcpMessage | null = null;
  let boundaryEventRef: AcpMessage | null = null;
  let showDebugLogs: boolean | undefined;
  let publishedItems = new WeakMap<ConversationItem, ConversationItem>();
  let publishedContexts = new WeakMap<TurnContext, PublishedTurnContext>();
  /** Timestamp of the last event fed to `b`, so a late arrival is detectable. */
  let lastProcessedTs = Number.NEGATIVE_INFINITY;

  function reset() {
    b = null;
    processedCount = 0;
    firstEventRef = null;
    boundaryEventRef = null;
    lastProcessedTs = Number.NEGATIVE_INFINITY;
    publishedItems = new WeakMap();
    publishedContexts = new WeakMap();
  }

  function update(
    events: AcpMessage[],
    isPromptPending: boolean | null,
    options?: BuildConversationOptions,
  ): BuildResult {
    const debug = options?.showDebugLogs;

    // Idle (not streaming): finalize the persistent builder in place instead of
    // re-parsing every event, but only when the append-only prefix is still
    // valid AND the events arriving with the idle flip carry on in ts-order.
    // Whatever the builder already consumed is in ts-order by construction, so
    // only the catch-up tail needs checking.
    if (isPromptPending === false) {
      const canFinalizeInPlace =
        b !== null &&
        debug === showDebugLogs &&
        events.length >= processedCount &&
        (processedCount === 0 || events[0] === firstEventRef) &&
        (processedCount === 0 ||
          events[processedCount - 1] === boundaryEventRef) &&
        extendsTimestampOrder(events, processedCount, lastProcessedTs);

      if (canFinalizeInPlace) {
        const builder = b as ItemBuilder;
        for (let i = processedCount; i < events.length; i++) {
          processEvent(builder, events[i], options);
        }
        finalizeBuilder(builder, isPromptPending);
        const result: BuildResult = {
          items: builder.items,
          stablePrefixItemCount: 0,
          lastTurnInfo: readLastTurnInfo(builder),
          isCompacting: builder.isCompacting,
          isClearing: builder.isClearing,
          completedToolCallCount: builder.completedToolCallCount,
          lastActivityAt: builder.lastActivityAt,
        };
        // A finalized builder can't be safely continued; the next streaming
        // call rebuilds fresh.
        reset();
        return result;
      }

      reset();
      return buildConversationItems(events, isPromptPending, options);
    }

    // The fast path is valid only when this call appends to the exact prefix we
    // already processed (events is append-only during streaming, immer hands us
    // a new array each push but keeps element identity) and the new events carry
    // on in ts-order. An event that lands behind what we already consumed would
    // otherwise render where it arrived rather than where it belongs — a user's
    // own message sitting under the reply it prompted, until the turn ended and
    // the thread re-sorted underneath them.
    const canAppend =
      b !== null &&
      debug === showDebugLogs &&
      events.length >= processedCount &&
      (processedCount === 0 || events[0] === firstEventRef) &&
      (processedCount === 0 ||
        events[processedCount - 1] === boundaryEventRef) &&
      extendsTimestampOrder(events, processedCount, lastProcessedTs);

    const didRebuild = !canAppend;
    if (didRebuild) {
      b = createItemBuilder();
      processedCount = 0;
      lastProcessedTs = Number.NEGATIVE_INFINITY;
      showDebugLogs = debug;
    }

    const builder = b as ItemBuilder;
    const hadProcessedEvents = processedCount > 0;
    builder.lowestTouchedItemIndex = Number.POSITIVE_INFINITY;
    // A rebuild re-reads the whole array, so order it first. An append continues
    // a sequence already in ts-order and takes the new events as they came.
    const ordered =
      processedCount === 0
        ? orderEventsByTimestamp(events, (event) => event.ts)
        : events;
    for (let i = processedCount; i < ordered.length; i++) {
      processEvent(builder, ordered[i], options);
    }
    processedCount = events.length;
    lastProcessedTs =
      ordered[ordered.length - 1]?.ts ?? Number.NEGATIVE_INFINITY;
    firstEventRef = events[0] ?? null;
    boundaryEventRef = events[processedCount - 1] ?? null;

    const turn = builder.currentTurn;
    const activeStart =
      turn && !turn.isComplete
        ? builder.currentTurnStartIndex
        : builder.items.length;

    // `buildConversationItems` always marks a trailing implicit turn complete.
    // Replicate that on the live turn's context so thought-completion matches;
    // it's safe to persist (a later real completion still flows through
    // `completePromptTurn`, which gates on `isComplete`, left untouched here).
    if (turn && turn.promptId === -1) {
      if (!turn.context.turnComplete) {
        turn.context.turnComplete = true;
        markTurnContextChanged(turn.context);
      }
    }

    const thoughtScanStart = didRebuild
      ? 0
      : Math.min(activeStart, builder.lowestTouchedItemIndex);
    markThoughtCompletion(builder.items, thoughtScanStart);

    // An event reached back across a turn boundary. Rebuild the visible snapshot
    // so cached rows observe it; the persistent builder remains valid.
    if (hadProcessedEvents && builder.lowestTouchedItemIndex < activeStart) {
      return buildConversationItems(events, isPromptPending, options);
    }

    // Published rows retain identity until their content or turn context
    // changes. Snapshot contexts keep later builder mutations out of results
    // already owned by a committed or abandoned render.
    return {
      items: publishConversationItems(
        builder.items,
        publishedItems,
        publishedContexts,
      ),
      stablePrefixItemCount: didRebuild ? 0 : activeStart,
      lastTurnInfo: readLastTurnInfoForOutput(builder),
      isCompacting: builder.isCompacting,
      isClearing: builder.isClearing,
      completedToolCallCount: builder.completedToolCallCount,
      lastActivityAt: builder.lastActivityAt,
    };
  }

  return { update, reset };
}

interface PublishedTurnContext {
  context: TurnContext;
  revision: number;
}

function publishConversationItems(
  items: ConversationItem[],
  publishedItems: WeakMap<ConversationItem, ConversationItem>,
  publishedContexts: WeakMap<TurnContext, PublishedTurnContext>,
): ConversationItem[] {
  const currentContexts = new WeakMap<TurnContext, TurnContext>();

  const publishContext = (context: TurnContext): TurnContext => {
    const current = currentContexts.get(context);
    if (current) return current;

    const existing = publishedContexts.get(context);
    const revision = readTurnContextRevision(context);
    if (existing?.revision === revision) {
      currentContexts.set(context, existing.context);
      return existing.context;
    }

    const published: TurnContext = {
      toolCalls: new Map(context.toolCalls),
      childItems: new Map(),
      turnCancelled: context.turnCancelled,
      turnComplete: context.turnComplete,
    };
    currentContexts.set(context, published);
    publishedContexts.set(context, { context: published, revision });
    for (const [parentId, children] of context.childItems) {
      published.childItems.set(parentId, publishItems(children));
    }
    return published;
  };

  const publishItems = (sourceItems: ConversationItem[]): ConversationItem[] =>
    sourceItems.map((item) => {
      if (item.type !== "session_update") return item;
      const existing = publishedItems.get(item);
      const publishedContext = publishContext(item.turnContext);
      if (
        existing?.type === "session_update" &&
        existing.thoughtComplete === item.thoughtComplete &&
        existing.turnContext === publishedContext
      ) {
        return existing;
      }
      const published = {
        ...item,
        turnContext: publishedContext,
      };
      publishedItems.set(item, published);
      return published;
    });

  return publishItems(items);
}

function readLastTurnInfoForOutput(b: ItemBuilder) {
  const info = readLastTurnInfo(b);
  if (!info) return null;
  // A trailing implicit turn reports complete (no prompt response will arrive
  // to flip it), mirroring `buildConversationItems`' finalization.
  if (b.currentTurn?.promptId === -1) {
    return { ...info, isComplete: true };
  }
  return info;
}
