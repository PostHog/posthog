import { CaretDownIcon, MagnifyingGlassIcon } from "@phosphor-icons/react";
import {
  Button,
  cn,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Text,
} from "@posthog/quill";
import { FeedQueryHighlight } from "@posthog/ui/features/canvas/components/FeedQueryInput";
import { useProjectTaskFeeds } from "@posthog/ui/features/canvas/hooks/useProjectTaskFeeds";
import { useNavigate } from "@tanstack/react-router";
import type { ReactElement } from "react";

/**
 * The header for a saved search. The current search name is a dropdown trigger
 * so a click lists every saved search in the project and switches to it in one
 * step, the way a space row switches spaces.
 */
export function SavedSearchSwitcher({
  currentFeedId,
  className,
}: {
  currentFeedId: string;
  className?: string;
}): ReactElement {
  const navigate = useNavigate();
  const feeds = useProjectTaskFeeds();
  const current = feeds.find((feed) => feed.id === currentFeedId);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            variant="default"
            size="sm"
            aria-label="Switch saved search"
            className={cn("min-w-0 gap-1", className)}
          >
            <MagnifyingGlassIcon
              size={12}
              className="shrink-0 text-muted-foreground/80"
            />
            <Text weight="semibold" className="min-w-0 truncate">
              {current?.name ?? "Saved search"}
            </Text>
            <CaretDownIcon
              size={12}
              className="shrink-0 text-muted-foreground"
            />
          </Button>
        }
      />
      <DropdownMenuContent
        align="start"
        side="bottom"
        sideOffset={4}
        className="min-w-72 max-w-96"
      >
        {feeds.length === 0 ? (
          <div className="px-2 py-1.5">
            <Text variant="muted" size="sm">
              No saved searches in this project.
            </Text>
          </div>
        ) : (
          feeds.map((feed) => (
            <DropdownMenuItem
              key={feed.id}
              onClick={() =>
                void navigate({
                  to: "/feeds/$feedId",
                  params: { feedId: feed.id },
                })
              }
              data-selected={feed.id === currentFeedId || undefined}
            >
              <div className="flex min-w-0 flex-col gap-0.5">
                <Text
                  weight={feed.id === currentFeedId ? "semibold" : "normal"}
                  className="min-w-0 truncate"
                >
                  {feed.name}
                </Text>
                <FeedQueryHighlight
                  query={feed.query}
                  className="min-w-0 truncate text-muted-foreground text-xs"
                />
              </div>
            </DropdownMenuItem>
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
