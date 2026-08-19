import {
  Item,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemSeparator,
  ItemTitle,
} from "@posthog/quill";
import type { Task } from "@posthog/shared/domain-types";
import {
  type ChannelActionItem,
  ChannelActionList,
} from "@posthog/ui/features/canvas/components/channelActions";
import { FeedQueryHighlight } from "@posthog/ui/features/canvas/components/FeedQueryInput";
import { useTaskFeedResults } from "@posthog/ui/features/canvas/hooks/useTaskFeedResults";
import type { TaskFeed } from "@posthog/ui/features/canvas/stores/taskFeedsStore";
import { DOT_TONE_VAR } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";

/** What the card is about: the feed row that is being pointed at. */
export interface FeedPreviewPayload {
  feed: TaskFeed;
  actions: ChannelActionItem[];
}

/** How many matching tasks the card names before falling back to the count. */
const MAX_PREVIEW_TASKS = 3;

const STATUS_DOT: Record<string, string> = {
  failed: DOT_TONE_VAR.red,
  in_progress: DOT_TONE_VAR.blue,
  completed: DOT_TONE_VAR.green,
  queued: DOT_TONE_VAR.yellow,
};

/** One matching task: the feed cards' status dot vocabulary, at a glance. */
function PreviewTaskRow({ task }: { task: Task }) {
  return (
    <span className="flex min-w-0 items-center gap-1.5">
      <span
        aria-hidden
        className="size-2 shrink-0 rounded-full"
        style={{
          backgroundColor:
            STATUS_DOT[task.latest_run?.status ?? ""] ?? DOT_TONE_VAR.gray,
        }}
      />
      <span className="truncate text-muted-foreground text-xs">
        {task.title}
      </span>
    </span>
  );
}

/**
 * The card itself, given everything it draws. Split from the hook wrapper so
 * a story can render it: the feed's results come from a query, and a query
 * resolves to nothing in Storybook.
 */
export function FeedPreviewContent({
  payload,
  tasks,
  /** Matching tasks, or `null` while the query hasn't answered yet. */
  total,
  onAction,
}: {
  payload: FeedPreviewPayload;
  tasks: Task[];
  total: number | null;
  onAction: () => void;
}) {
  const { feed, actions } = payload;
  return (
    <ItemGroup className="gap-0!">
      <Item size="xs" className="flex-nowrap p-2">
        <ItemContent className="min-w-0 gap-1">
          <ItemTitle className="break-words">{feed.name}</ItemTitle>
          <ItemDescription>
            {/* No count until the query answers: "0 tasks" on a feed that has
                them is a wrong answer, and the card is about to have a right
                one. */}
            {total == null
              ? "Feed"
              : `Feed \u00b7 ${total} ${total === 1 ? "task" : "tasks"}`}
          </ItemDescription>
          <FeedQueryHighlight
            query={feed.query}
            className="block truncate text-xs"
          />
        </ItemContent>
      </Item>
      {tasks.length > 0 && (
        <>
          <ItemSeparator className="my-0" />
          <div className="flex flex-col gap-1 p-2">
            {tasks.slice(0, MAX_PREVIEW_TASKS).map((task) => (
              <PreviewTaskRow key={task.id} task={task} />
            ))}
          </div>
        </>
      )}
      <ItemSeparator className="my-0" />
      <div className="p-1">
        <ChannelActionList actions={actions} onAction={onAction} />
      </div>
    </ItemGroup>
  );
}

/**
 * The contents of a feed row's hover card: what the feed is called, the query
 * behind it, how much it matches right now, its freshest matches, and what
 * you can do to it.
 *
 * Rendered by the one card the sidebar shares, from the payload of whichever
 * trigger is active — so the feed's query runs for the row being pointed at,
 * once, rather than once per feed in the list.
 */
export function FeedPreview({
  payload,
  onAction,
}: {
  payload: FeedPreviewPayload;
  onAction: () => void;
}) {
  const { tasks, isLoading } = useTaskFeedResults(payload.feed.query);
  return (
    <FeedPreviewContent
      payload={payload}
      tasks={tasks}
      total={isLoading ? null : tasks.length}
      onAction={onAction}
    />
  );
}
