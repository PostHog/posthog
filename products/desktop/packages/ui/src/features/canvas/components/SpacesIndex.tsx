import { MagnifyingGlassIcon, PlusIcon, StarIcon } from "@phosphor-icons/react";
import {
  Button,
  Card,
  CardContent,
  cn,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
  MenuLabel,
  Skeleton,
  Text,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { CreateChannelModal } from "@posthog/ui/features/canvas/components/CreateChannelModal";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import { SpacesIcon } from "@posthog/ui/features/canvas/components/SpacesIcon";
import { useChannelStarToggle } from "@posthog/ui/features/canvas/hooks/useChannelStars";
import {
  type Channel,
  useChannels,
} from "@posthog/ui/features/canvas/hooks/useChannels";
import { track } from "@posthog/ui/shell/analytics";
import { Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";

/**
 * The star, as a control rather than a mark. This page is where a space is
 * found, and starring it is what puts it in the Work column — so the star has
 * to be the thing you click, not a badge saying someone already did.
 */
function StarToggle({ channel }: { channel: Channel }) {
  const { isStarred, toggleStar } = useChannelStarToggle(channel);
  const label = isStarred ? "Remove from Work" : "Add to Work";
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="default"
            size="icon-sm"
            aria-label={label}
            // Always drawn: this page exists to star spaces, and a control
            // that only appears under the pointer does not say so.
            className={cn(
              "shrink-0",
              isStarred
                ? "text-warning"
                : "text-muted-foreground/50 transition-colors group-hover/space:text-muted-foreground",
            )}
            onClick={(event) => {
              // The card is a link; starring is not a way into the space.
              event.preventDefault();
              event.stopPropagation();
              track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
                action_type: isStarred ? "unstar" : "star",
                surface: "spaces_index",
                channel_id: channel.id,
              });
              toggleStar();
            }}
          >
            <StarIcon size={14} weight={isStarred ? "fill" : "regular"} />
          </Button>
        }
      />
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

function SpaceCard({ channel }: { channel: Channel }) {
  const personal = channel.channelType === "personal";

  return (
    <Link
      to="/spaces/$channelId"
      params={{ channelId: channel.id }}
      className="group/space no-underline"
    >
      <Card className="h-full transition-colors hover:bg-fill-hover">
        <CardContent className="flex flex-col gap-2 p-4">
          <div className="flex min-w-0 items-center gap-1.5">
            {channelGlyph(channel.name, {
              size: 14,
              personal,
              private: channel.channelType === "private",
            })}
            {/* One hash: the glyph draws it, so the name must not. */}
            <Text weight="semibold" className="min-w-0 flex-1 truncate">
              {channel.name}
            </Text>
            {!personal && <StarToggle channel={channel} />}
          </div>
          <Text size="sm" variant="muted" className="truncate">
            {channel.repositories.length > 0
              ? channel.repositories.join(", ")
              : "No repositories wired up"}
          </Text>
        </CardContent>
      </Card>
    </Link>
  );
}

function SpaceGrid({ channels }: { channels: Channel[] }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3">
      {channels.map((channel) => (
        <SpaceCard key={channel.id} channel={channel} />
      ))}
    </div>
  );
}

/**
 * The `/spaces` page: every space in the project, where you find the ones you
 * work in and star them into the Work column, and where you make a new one.
 *
 * A page rather than a redirect to the first space. The rail can put you here,
 * and a destination you cannot rest on is one the rail cannot return you to.
 */
export function SpacesIndex() {
  const { channels, isLoading } = useChannels();
  const [createOpen, setCreateOpen] = useState(false);
  const [query, setQuery] = useState("");

  const needle = query.trim().toLowerCase();
  const { starred, rest } = useMemo(() => {
    const shown = needle
      ? channels.filter((c) => c.name.toLowerCase().includes(needle))
      : channels;
    return {
      starred: shown.filter((c) => c.starred || c.channelType === "personal"),
      rest: shown.filter((c) => !c.starred && c.channelType !== "personal"),
    };
  }, [channels, needle]);
  const noMatches = starred.length === 0 && rest.length === 0;

  return (
    <div className="h-full overflow-auto bg-gray-1">
      <div className="mx-auto w-full max-w-5xl px-6 py-6">
        <div className="mb-1 flex items-center justify-between gap-3">
          <Text size="lg" weight="semibold">
            Spaces
          </Text>
          <Button variant="primary" onClick={() => setCreateOpen(true)}>
            <PlusIcon size={14} />
            New space…
          </Button>
        </div>
        <Text size="sm" variant="muted">
          Star a space to keep it in your Work column.
        </Text>

        <InputGroup className="mt-4 mb-5 max-w-sm">
          <InputGroupAddon>
            <MagnifyingGlassIcon size={14} aria-hidden />
          </InputGroupAddon>
          <InputGroupInput
            value={query}
            placeholder="Search spaces…"
            aria-label="Search spaces"
            onChange={(event) => setQuery(event.target.value)}
          />
        </InputGroup>

        {isLoading ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-[86px] w-full" />
            ))}
          </div>
        ) : channels.length === 0 ? (
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <SpacesIcon size={20} />
              </EmptyMedia>
              <EmptyTitle>No spaces yet</EmptyTitle>
              <EmptyDescription>
                A space gets its own sessions, canvases, and context.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : noMatches ? (
          <Text size="sm" variant="muted">
            No space by that name.
          </Text>
        ) : (
          <div className="flex flex-col gap-6">
            {starred.length > 0 && (
              <div>
                <MenuLabel className="mb-2 px-0">In your Work column</MenuLabel>
                <SpaceGrid channels={starred} />
              </div>
            )}
            {rest.length > 0 && (
              <div>
                {starred.length > 0 && (
                  <MenuLabel className="mb-2 px-0">Everything else</MenuLabel>
                )}
                <SpaceGrid channels={rest} />
              </div>
            )}
          </div>
        )}
      </div>
      <CreateChannelModal open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}
