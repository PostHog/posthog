import { XIcon } from "@phosphor-icons/react";
import { suggestFeedName } from "@posthog/core/tasks/feedQuery";
import { Button, cn, Spinner } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { FeedQueryInput } from "@posthog/ui/features/canvas/components/FeedQueryInput";
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
import { useEffect, useState } from "react";

const MAX_FEED_NAME_LENGTH = 80;
const PREVIEW_DEBOUNCE_MS = 400;

/**
 * Create or edit a custom feed: the query its cards come from, plus a name.
 *
 * The query leads — it is what a feed is — with the suggestion panel inline
 * under it and the live match count beside the label, so a bad query is
 * visible before it is saved. The name follows and writes itself from the
 * query ("created-by:@me pr:any" suggests "My tasks with a PR") until it is
 * edited by hand, so naming a feed costs nothing. Pass `feed` to edit; without
 * one the modal creates and hands the new feed to `onCreated` so the caller
 * can open it right away.
 */
export function TaskFeedModal({
  open,
  onOpenChange,
  feed,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The feed being edited; absent when creating a new one. */
  feed?: TaskFeed;
  onCreated?: (feed: TaskFeed) => void;
}) {
  const addFeed = useTaskFeedsStore((s) => s.addFeed);
  const updateFeed = useTaskFeedsStore((s) => s.updateFeed);
  const [name, setName] = useState(feed?.name ?? "");
  const [query, setQuery] = useState(feed?.query ?? "");
  // Until the name is touched it follows the query; an existing feed's name
  // was already chosen, so editing never rewrites it.
  const [nameEdited, setNameEdited] = useState(!!feed);

  // Seed the fields each time the modal opens, so a reopened create modal
  // starts clean and an edit always shows the feed's current values.
  useEffect(() => {
    if (!open) return;
    setName(feed?.name ?? "");
    setQuery(feed?.query ?? "");
    setNameEdited(!!feed);
  }, [open, feed]);

  const setQueryAndSuggestName = (next: string) => {
    setQuery(next);
    if (!nameEdited) setName(suggestFeedName(next));
  };

  const trimmedName = name.trim();
  const trimmedQuery = query.trim();
  const canSubmit = trimmedName !== "" && trimmedQuery !== "";

  // Live preview: what the query matches right now, debounced so each
  // keystroke doesn't become a request.
  const { debounced: previewQuery, isPending } = useDebouncedValue(
    open ? trimmedQuery : "",
    PREVIEW_DEBOUNCE_MS,
  );
  const preview = useTaskFeedResults(previewQuery);
  // Issues come from the undebounced plan, so a typo is flagged the moment
  // it is typed rather than after the debounce settles.
  const { plan } = useFeedQueryPlan(open ? trimmedQuery : "");
  const issue = plan?.issues[0];
  const counting = trimmedQuery !== "" && (isPending || preview.isLoading);

  const submit = () => {
    if (!canSubmit) return;
    if (feed) {
      updateFeed(feed.id, { name: trimmedName, query: trimmedQuery });
      track(ANALYTICS_EVENTS.TASK_FEED_ACTION, {
        action_type: "update",
        surface: "sidebar",
        feed_id: feed.id,
        query_length: trimmedQuery.length,
      });
    } else {
      const created = addFeed({ name: trimmedName, query: trimmedQuery });
      track(ANALYTICS_EVENTS.TASK_FEED_ACTION, {
        action_type: "create",
        surface: "sidebar",
        feed_id: created.id,
        query_length: trimmedQuery.length,
      });
      onCreated?.(created);
    }
    onOpenChange(false);
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      {/* overflow-visible: the query editor's suggestion popup hangs below
          the field, and the dialog's default overflow:auto would clip it. */}
      <Dialog.Content maxWidth="520px" className="overflow-visible!">
        <Flex align="start" justify="between" gap="3">
          <Flex direction="column" gap="1">
            <Dialog.Title mb="0">
              <Text className="font-semibold text-base">
                {feed ? "Edit feed" : "New feed"}
              </Text>
            </Dialog.Title>
            <Dialog.Description>
              <Text className="text-(--gray-9) text-sm">
                A feed is a saved search that keeps up with matching tasks.
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
          {/* The label row carries the live match count: pinned up here it
              never moves, and it reads as the query's own answer. */}
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
            value={query}
            onChange={setQueryAndSuggestName}
            onSubmit={submit}
            placeholder="e.g. billing created-by:@me -status:failed"
          />
          {/* Fixed-height meta row: the first problem with the query, or the
              syntax reminder. Space is reserved either way, so typing never
              moves the fields. */}
          <div
            className={cn(
              "h-5 min-w-0 truncate text-xs",
              issue
                ? issue.kind === "unsupported"
                  ? "text-(--amber-11)"
                  : "text-(--red-11)"
                : "text-(--gray-9)",
            )}
            title={issue?.message}
          >
            {issue?.message ??
              "Free text searches tasks. Same filter twice is either, -filter excludes."}
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
              // Clearing the name hands it back to the query's suggestion.
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
            {feed ? "Save" : "Create feed"}
          </Button>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
