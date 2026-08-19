import { XIcon } from "@phosphor-icons/react";
import { parseFeedQuery, suggestFeedName } from "@posthog/core/tasks/feedQuery";
import { Button, cn, Spinner } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { FeedQueryInput } from "@posthog/ui/features/canvas/components/FeedQueryInput";
import { unfinishedFilterKeys } from "@posthog/ui/features/canvas/components/feedQuerySuggestions";
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
import { Dialog, Flex, IconButton, Text, TextField } from "@radix-ui/themes";
import { useEffect, useMemo, useState } from "react";

const MAX_FEED_NAME_LENGTH = 80;
const PREVIEW_DEBOUNCE_MS = 400;

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
  const seedQuery = feed?.query ?? initialQuery ?? "";
  const [name, setName] = useState(
    feed?.name ?? (seedQuery ? suggestFeedName(seedQuery) : ""),
  );
  const [query, setQuery] = useState(seedQuery);
  const [nameEdited, setNameEdited] = useState(!!feed);

  useEffect(() => {
    if (!open) return;
    const nextQuery = feed?.query ?? initialQuery ?? "";
    setName(feed?.name ?? (nextQuery ? suggestFeedName(nextQuery) : ""));
    setQuery(nextQuery);
    setNameEdited(!!feed);
  }, [open, feed, initialQuery]);

  const setQueryAndSuggestName = (next: string) => {
    setQuery(next);
    if (!nameEdited) setName(suggestFeedName(next));
  };

  const trimmedName = name.trim();
  const trimmedQuery = query.trim();
  const canSubmit =
    trimmedName !== "" &&
    trimmedQuery !== "" &&
    (feed !== undefined || projectId !== null);

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
      if (projectId === null) return;
      const created = addFeed({
        name: trimmedName,
        query: trimmedQuery,
        projectId,
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
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Content maxWidth="520px" className="overflow-visible!">
        <Flex align="start" justify="between" gap="3">
          <Flex direction="column" gap="1">
            <Dialog.Title mb="0">
              <Text className="font-semibold text-base">
                {feed ? "Edit saved search" : "Save search"}
              </Text>
            </Dialog.Title>
            <Dialog.Description>
              <Text className="text-(--gray-9) text-sm">
                A saved search keeps up with matching tasks, ready to reopen
                from the palette.
              </Text>
            </Dialog.Description>
          </Flex>
          <Dialog.Close>
            <IconButton
              variant="ghost"
              color="gray"
              size="2"
              aria-label="Close"
            >
              <XIcon size={18} />
            </IconButton>
          </Dialog.Close>
        </Flex>

        <Flex direction="column" gap="2" mt="4">
          <Flex align="center" justify="between" gap="3">
            <Text
              as="label"
              htmlFor="task-feed-query"
              className="font-medium text-sm"
            >
              Query
            </Text>
            <span className="flex shrink-0 items-center gap-1.5 text-(--gray-9) text-xs tabular-nums">
              {counting ? (
                <Spinner className="size-3" />
              ) : (
                previewQuery !== "" &&
                (preview.tasks.length === 1
                  ? "1 task matches"
                  : `${preview.tasks.length} tasks match`)
              )}
            </span>
          </Flex>
          <FeedQueryInput
            id="task-feed-query"
            autoFocus
            openOnFocus={false}
            value={query}
            onChange={setQueryAndSuggestName}
            onSubmit={submit}
            placeholder="e.g. billing created-by:@me -status:failed"
          />
          <div
            className={cn(
              "h-5 min-w-0 truncate text-xs",
              issue
                ? issue.kind === "unsupported"
                  ? "text-(--amber-11)"
                  : "text-(--red-11)"
                : unfinished
                  ? "text-(--amber-11)"
                  : "text-(--gray-9)",
            )}
            title={issue?.message}
          >
            {issue?.message ??
              (unfinished
                ? `"${unfinished.word}" is searched as text. Did you mean ${unfinished.keys.slice(0, 2).join(" or ")}?`
                : "Free text searches tasks. Same filter twice is either, -filter excludes.")}
          </div>
        </Flex>

        <Flex direction="column" gap="2">
          <Text
            as="label"
            htmlFor="task-feed-name"
            className="font-medium text-sm"
          >
            Name
          </Text>
          <TextField.Root
            id="task-feed-name"
            size="2"
            value={name}
            placeholder="Named after the query as you type"
            maxLength={MAX_FEED_NAME_LENGTH}
            onChange={(e) => {
              setName(e.target.value);
              setNameEdited(e.target.value.trim() !== "");
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                submit();
              }
            }}
          />
        </Flex>

        <Flex gap="3" mt="5" justify="end">
          <Dialog.Close>
            <Button variant="outline">Cancel</Button>
          </Dialog.Close>
          <Button variant="primary" disabled={!canSubmit} onClick={submit}>
            {feed ? "Save" : "Save search"}
          </Button>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
