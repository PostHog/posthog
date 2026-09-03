import { parseFeedQuery, suggestFeedName } from "@posthog/core/tasks/feedQuery";
import {
  Button,
  cn,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Spinner,
} from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { FeedQueryInput } from "@posthog/ui/features/canvas/components/FeedQueryInput";
import { unfinishedFilterKeys } from "@posthog/ui/features/canvas/components/feedQuerySuggestionUtils";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import {
  useFeedQueryPlan,
  useTaskFeedResults,
} from "@posthog/ui/features/canvas/hooks/useTaskFeedResults";
import {
  type TaskFeed,
  useTaskFeedsStore,
} from "@posthog/ui/features/canvas/stores/taskFeedsStore";
import { useDebouncedValue } from "@posthog/ui/primitives/hooks/useDebouncedValue";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useMemo, useRef, useState } from "react";

const MAX_FEED_NAME_LENGTH = 80;
const PREVIEW_DEBOUNCE_MS = 400;
const PREVIEW_TASK_LIMIT = 4;

export function TaskFeedModal({
  open,
  onOpenChange,
  feed,
  initialQuery,
  surface = "sidebar",
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  feed?: TaskFeed;
  initialQuery?: string;
  surface?: "sidebar" | "command_menu";
  onCreated?: (feed: TaskFeed) => void;
}) {
  const addFeed = useTaskFeedsStore((s) => s.addFeed);
  const updateFeed = useTaskFeedsStore((s) => s.updateFeed);
  const projectId = useAuthStateValue((s) => s.currentProjectId);
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });
  const { channels } = useChannels();
  const ownerId = currentUser?.uuid ?? null;
  const seedQuery = feed?.query ?? initialQuery ?? "";
  const [name, setName] = useState(
    feed?.name ?? (seedQuery ? suggestFeedName(seedQuery) : ""),
  );
  const [query, setQuery] = useState(seedQuery);
  const nameEdited = useRef(!!feed);

  useEffect(() => {
    if (!open) return;
    const nextQuery = feed?.query ?? initialQuery ?? "";
    setName(feed?.name ?? (nextQuery ? suggestFeedName(nextQuery) : ""));
    setQuery(nextQuery);
    nameEdited.current = !!feed;
  }, [open, feed, initialQuery]);

  const setQueryAndSuggestName = (next: string) => {
    setQuery(next);
    if (!nameEdited.current) setName(suggestFeedName(next));
  };

  const trimmedName = name.trim();
  const trimmedQuery = query.trim();
  const canSubmit =
    trimmedName !== "" &&
    trimmedQuery !== "" &&
    (feed !== undefined || (projectId !== null && ownerId !== null));

  const { debounced: previewQuery, isPending } = useDebouncedValue(
    open ? trimmedQuery : "",
    PREVIEW_DEBOUNCE_MS,
  );
  const preview = useTaskFeedResults(previewQuery);
  const { plan } = useFeedQueryPlan(open ? trimmedQuery : "");
  const issue = plan?.issues[0];
  const unfinished = useMemo(() => {
    const parsedText = parseFeedQuery(trimmedQuery).text;
    return unfinishedFilterKeys(parsedText)[0];
  }, [trimmedQuery]);
  const counting = trimmedQuery !== "" && (isPending || preview.isLoading);
  const hasPreview = trimmedQuery !== "" && previewQuery !== "";
  const previewTasks = preview.tasks.slice(0, PREVIEW_TASK_LIMIT);
  const previewOverflow = hasPreview
    ? preview.tasks.length - previewTasks.length
    : 0;
  const channelNames = useMemo(
    () => new Map(channels.map((channel) => [channel.id, channel.name])),
    [channels],
  );

  const submit = () => {
    if (!canSubmit) return;
    if (feed) {
      updateFeed(feed.id, { name: trimmedName, query: trimmedQuery });
      track(ANALYTICS_EVENTS.TASK_FEED_ACTION, {
        action_type: "update",
        surface,
        feed_id: feed.id,
        query_length: trimmedQuery.length,
      });
    } else {
      if (projectId === null || ownerId === null) return;
      const created = addFeed({
        name: trimmedName,
        query: trimmedQuery,
        projectId,
        ownerId,
      });
      track(ANALYTICS_EVENTS.TASK_FEED_ACTION, {
        action_type: "create",
        surface,
        feed_id: created.id,
        query_length: trimmedQuery.length,
      });
      onCreated?.(created);
    }
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="overflow-visible sm:max-w-xl">
        <DialogHeader className="min-w-0">
          <DialogTitle>
            {feed ? "Edit saved search" : "Save search"}
          </DialogTitle>
          <DialogDescription>
            A saved search updates when tasks match its query. Reopen it from
            the command palette.
          </DialogDescription>
        </DialogHeader>
        <DialogBody
          render={<div />}
          className="flex min-w-0 flex-col gap-4 overflow-y-auto py-4"
        >
          <div className="flex flex-col gap-1.5">
            <label htmlFor="task-feed-name" className="font-medium text-sm">
              Name
            </label>
            <Input
              id="task-feed-name"
              value={name}
              placeholder="Name based on the query"
              maxLength={MAX_FEED_NAME_LENGTH}
              onChange={(event) => {
                setName(event.target.value);
                nameEdited.current = event.target.value.trim() !== "";
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  submit();
                }
              }}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="task-feed-query" className="font-medium text-sm">
              Query
            </label>
            <FeedQueryInput
              id="task-feed-query"
              autoFocus
              openOnFocus={false}
              value={query}
              onChange={setQueryAndSuggestName}
              onSubmit={submit}
              placeholder="Example: billing created-by:@me -status:failed"
            />
            <div
              className={cn(
                "min-h-5 min-w-0 truncate text-xs",
                preview.error || issue
                  ? issue?.kind === "unsupported" && !preview.error
                    ? "text-(--amber-11)"
                    : "text-destructive"
                  : unfinished
                    ? "text-(--amber-11)"
                    : "text-muted-foreground",
              )}
              title={issue?.message}
            >
              {preview.error
                ? preview.errorMessage
                : (issue?.message ??
                  (unfinished
                    ? `"${unfinished.word}" is searched as text. Did you mean ${unfinished.keys.slice(0, 2).join(" or ")}?`
                    : "Free text searches task titles. Repeat a filter to match either value. Use - to exclude a filter."))}
            </div>
          </div>
          <div className="flex min-h-24 flex-1 basis-40 flex-col overflow-hidden rounded-lg border border-border bg-muted/40">
            <div className="flex h-8 shrink-0 items-center gap-2 border-border border-b px-3 text-muted-foreground text-xs">
              <span className="font-medium">Matches</span>
              <span className="ml-auto flex items-center gap-1.5 tabular-nums">
                {counting ? (
                  <Spinner className="size-3" />
                ) : preview.error && preview.canRetry ? (
                  <Button
                    variant="link-muted"
                    size="xs"
                    loading={preview.isFetching}
                    disabled={preview.isFetching}
                    onClick={preview.refetch}
                  >
                    Try again
                  </Button>
                ) : preview.error ? null : (
                  hasPreview &&
                  preview.tasks.length > 0 &&
                  (preview.isComplete
                    ? preview.tasks.length === 1
                      ? "1 task matches"
                      : `${preview.tasks.length} tasks match`
                    : "Some matches may not be shown")
                )}
              </span>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">
              {!hasPreview || counting ? (
                <p className="px-3 py-6 text-center text-muted-foreground text-xs">
                  Matching tasks appear here as you type.
                </p>
              ) : previewTasks.length === 0 ? (
                <p className="px-3 py-6 text-center text-muted-foreground text-xs">
                  No tasks match this query yet.
                </p>
              ) : (
                previewTasks.map((task) => (
                  <div
                    key={task.id}
                    className="flex items-center gap-2 border-border/60 border-b px-3 py-1.5 text-xs last:border-b-0"
                  >
                    <span className="min-w-0 flex-1 truncate">
                      {task.title}
                    </span>
                    {task.channel && channelNames.get(task.channel) && (
                      <span className="shrink-0 text-muted-foreground">
                        {channelNames.get(task.channel)}
                      </span>
                    )}
                    <span className="w-8 shrink-0 text-right text-muted-foreground tabular-nums">
                      {formatRelativeTimeShort(
                        task.last_activity_at ?? task.updated_at,
                      )}
                    </span>
                  </div>
                ))
              )}
            </div>
            {previewOverflow > 0 && (
              <div className="shrink-0 border-border border-t px-3 py-1.5 text-muted-foreground text-xs">
                and {previewOverflow} more
              </div>
            )}
          </div>
        </DialogBody>
        <DialogFooter className="min-w-0">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!canSubmit} onClick={submit}>
            {feed ? "Save" : "Save search"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
