import { XIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import {
  type TaskFeed,
  useTaskFeedsStore,
} from "@posthog/ui/features/canvas/stores/taskFeedsStore";
import { track } from "@posthog/ui/shell/analytics";
import { Dialog, Flex, IconButton, Text, TextField } from "@radix-ui/themes";
import { useEffect, useState } from "react";

const MAX_FEED_NAME_LENGTH = 80;
const MAX_FEED_QUERY_LENGTH = 512;

/**
 * Create or edit a custom feed: a name plus the query its cards come from.
 * Pass `feed` to edit; without one the modal creates and hands the new feed
 * to `onCreated` so the caller can open it right away.
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

  // Seed the fields each time the modal opens, so a reopened create modal
  // starts clean and an edit always shows the feed's current values.
  useEffect(() => {
    if (!open) return;
    setName(feed?.name ?? "");
    setQuery(feed?.query ?? "");
  }, [open, feed]);

  const trimmedName = name.trim();
  const trimmedQuery = query.trim();
  const canSubmit = trimmedName !== "" && trimmedQuery !== "";

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

  const onFieldKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      submit();
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Content maxWidth="560px">
        <Flex align="start" justify="between" gap="3">
          <Dialog.Title>
            <Text className="font-bold text-lg">
              {feed ? "Edit feed" : "New feed"}
            </Text>
          </Dialog.Title>
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
          <Text
            as="label"
            htmlFor="task-feed-name"
            className="font-medium text-sm"
          >
            Name
          </Text>
          <TextField.Root
            id="task-feed-name"
            autoFocus
            size="3"
            value={name}
            placeholder="e.g. Billing work"
            maxLength={MAX_FEED_NAME_LENGTH}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={onFieldKeyDown}
          />
        </Flex>

        <Flex direction="column" gap="2" mt="4">
          <Text
            as="label"
            htmlFor="task-feed-query"
            className="font-medium text-sm"
          >
            Query
          </Text>
          <TextField.Root
            id="task-feed-query"
            size="3"
            value={query}
            placeholder="e.g. billing"
            maxLength={MAX_FEED_QUERY_LENGTH}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onFieldKeyDown}
          />
          <Text className="text-gray-9 text-sm">
            The feed shows tasks whose title, description, or number match this
            text.
          </Text>
        </Flex>

        <Flex gap="3" mt="5" justify="end">
          <Button variant="primary" disabled={!canSubmit} onClick={submit}>
            {feed ? "Save" : "Create feed"}
          </Button>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
