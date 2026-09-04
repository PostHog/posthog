import { CaretDownIcon, CheckIcon } from "@phosphor-icons/react";
import {
  Button,
  cn,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Text,
} from "@posthog/quill";
import { useProjectTaskFeeds } from "@posthog/ui/features/canvas/hooks/useProjectTaskFeeds";
import { useNavigate } from "@tanstack/react-router";
import type { ReactElement } from "react";

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
            className={cn("-ml-1.5 min-w-0 shrink gap-1 px-1.5", className)}
          >
            <span className="min-w-0 truncate font-bold text-base">
              {current?.name ?? "Saved search"}
            </span>
            <CaretDownIcon
              size={12}
              weight="bold"
              className="shrink-0 text-muted-foreground"
            />
          </Button>
        }
      />
      <DropdownMenuContent
        align="start"
        side="bottom"
        sideOffset={6}
        className="min-w-64 max-w-80"
      >
        {feeds.length === 0 ? (
          <div className="px-2 py-1.5">
            <Text variant="muted" size="sm">
              No saved searches in this project yet.
            </Text>
          </div>
        ) : (
          feeds.map((feed) => {
            const isCurrent = feed.id === currentFeedId;
            return (
              <DropdownMenuItem
                key={feed.id}
                onClick={() =>
                  void navigate({
                    to: "/feeds/$feedId",
                    params: { feedId: feed.id },
                  })
                }
              >
                <CheckIcon
                  size={12}
                  weight="bold"
                  className={cn("shrink-0", !isCurrent && "opacity-0")}
                />
                <span
                  className={cn(
                    "min-w-0 truncate",
                    isCurrent && "font-semibold",
                  )}
                >
                  {feed.name}
                </span>
              </DropdownMenuItem>
            );
          })
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
