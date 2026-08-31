import {
  MagnifyingGlassIcon,
  PlusIcon,
  TrashIcon,
} from "@phosphor-icons/react";
import {
  Button,
  Card,
  CardContent,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Text,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { FeedQueryHighlight } from "@posthog/ui/features/canvas/components/FeedQueryInput";
import { useProjectTaskFeeds } from "@posthog/ui/features/canvas/hooks/useProjectTaskFeeds";
import { useTaskFeedsStore } from "@posthog/ui/features/canvas/stores/taskFeedsStore";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useNavigate } from "@tanstack/react-router";
import { useMemo } from "react";

/**
 * The `/feeds` page: every saved search in the project.
 *
 * A page rather than a redirect to the first search. The rail can put you here,
 * and a destination you cannot rest on is one the rail cannot return you to.
 */
export function SavedSearchesIndex() {
  const navigate = useNavigate();
  const feeds = useProjectTaskFeeds();
  const removeFeed = useTaskFeedsStore((state) => state.removeFeed);

  useSetHeaderContent(
    useMemo(
      () => (
        <div className="flex min-w-0 items-center gap-1.5 px-1 text-[13px]">
          <MagnifyingGlassIcon
            size={12}
            className="shrink-0 text-muted-foreground/80"
          />
          <Text weight="semibold">Saved searches</Text>
        </div>
      ),
      [],
    ),
  );

  const handleDelete = (feedId: string, name: string) => {
    removeFeed(feedId);
    track(ANALYTICS_EVENTS.TASK_FEED_ACTION, {
      action_type: "delete",
      surface: "feed_home",
      feed_id: feedId,
    });
    toast.success(`Deleted “${name}”`);
  };

  return (
    <div className="h-full overflow-auto bg-gray-1">
      <div className="mx-auto w-full max-w-5xl px-6 py-6">
        <div className="mb-4 flex items-center justify-between gap-3">
          <Text size="lg" weight="semibold">
            Saved searches
          </Text>
          <Button
            variant="primary"
            onClick={() => {
              track(ANALYTICS_EVENTS.SIDEBAR_NAV_ITEM_CLICKED, {
                item: "search",
                in_more: false,
                layout: "channels",
              });
              void navigate({ to: "/spaces" });
            }}
          >
            <PlusIcon size={14} />
            New search
          </Button>
        </div>

        {feeds.length === 0 ? (
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <MagnifyingGlassIcon size={20} />
              </EmptyMedia>
              <EmptyTitle>No saved searches yet</EmptyTitle>
              <EmptyDescription>
                Search for tasks from the command bar, then save it to find it
                here later.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3">
            {feeds.map((feed) => (
              <Card
                key={feed.id}
                className="group h-full transition-colors hover:bg-fill-hover"
              >
                <CardContent className="flex flex-col gap-2 p-4">
                  <button
                    type="button"
                    className="flex min-w-0 flex-col gap-1 text-left"
                    onClick={() =>
                      void navigate({
                        to: "/feeds/$feedId",
                        params: { feedId: feed.id },
                      })
                    }
                  >
                    <Text weight="semibold" className="truncate">
                      {feed.name}
                    </Text>
                    <FeedQueryHighlight
                      query={feed.query}
                      className="min-w-0 truncate text-muted-foreground text-sm"
                    />
                  </button>
                  <div className="flex justify-end">
                    <Button
                      variant="outline"
                      size="xs"
                      aria-label={`Delete saved search ${feed.name}`}
                      onClick={() => handleDelete(feed.id, feed.name)}
                    >
                      <TrashIcon size={12} />
                      Delete
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
