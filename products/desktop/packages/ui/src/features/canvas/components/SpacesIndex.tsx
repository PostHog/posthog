import { MagnifyingGlassIcon, PlusIcon, StarIcon } from "@phosphor-icons/react";
import {
  Button,
  cn,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
  Skeleton,
  Text,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { CreateChannelModal } from "@posthog/ui/features/canvas/components/CreateChannelModal";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import { PresenceAvatars } from "@posthog/ui/features/canvas/components/PresenceAvatars";
import { SpacesIcon } from "@posthog/ui/features/canvas/components/SpacesIcon";
import { useChannelStarToggle } from "@posthog/ui/features/canvas/hooks/useChannelStars";
import {
  type Channel,
  useChannels,
} from "@posthog/ui/features/canvas/hooks/useChannels";
import { useSpaceParticipants } from "@posthog/ui/features/canvas/hooks/useSpaceParticipants";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { useInView } from "@posthog/ui/primitives/hooks/useInView";
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
  // "Star" rather than "add to the Work column": the section above is called
  // Starred, and a control should be named after what it does.
  const label = isStarred ? "Unstar space" : "Star space";
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="default"
            size="icon-sm"
            aria-label={label}
            // A starred row keeps its star; an unstarred one shows a faint one
            // that firms up under the pointer. Hiding it outright would leave
            // the page with no visible way to do the thing it is for.
            className={cn(
              "shrink-0",
              isStarred
                ? "text-warning"
                : "text-muted-foreground/40 group-hover/space:text-muted-foreground",
            )}
            onClick={(event) => {
              // The row is a link; starring is not a way into the space.
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

/** Faces drawn before the rest become a count. */
const FACES_PER_ROW = 3;

/**
 * A row, not a card. A space here is a name, what it is wired to and what you
 * have going on in it; a box drawn around that spent a whole screen on fifteen
 * of them.
 */
function SpaceRow({ channel }: { channel: Channel }) {
  // Only rows you can see ask who is in them: a request per row is a storm for
  // a list most of which you scroll straight past.
  const [ref, inView] = useInView<HTMLAnchorElement>({
    rootMargin: "300px 0px",
    once: true,
  });
  const { people } = useSpaceParticipants(channel.id, { enabled: inView });
  const personal = channel.channelType === "personal";
  const repositories = channel.repositories.join(", ");

  return (
    <Link
      ref={ref}
      to="/spaces/$channelId"
      params={{ channelId: channel.id }}
      className="group/space flex h-8 items-center gap-3 rounded-(--radius-2) pr-1 pl-2 no-underline transition-colors hover:bg-fill-hover"
    >
      {channelGlyph(channel.name, {
        size: 13,
        personal,
        private: channel.channelType === "private",
      })}
      {/* One hash: the glyph draws it, so the name must not. */}
      <Text size="sm" weight="medium" className="min-w-0 shrink-0 truncate">
        {channel.name}
      </Text>
      <Text size="xxs" variant="muted" className="min-w-0 flex-1 truncate">
        {repositories}
      </Text>
      {people.length > 0 && (
        <span className="flex shrink-0 items-center gap-1">
          {/* No live dots and no crown: the question is who has worked here,
              not who is at their desk or who opened the space. */}
          <PresenceAvatars
            people={people.slice(0, FACES_PER_ROW)}
            className="shrink-0"
          />
          {people.length > FACES_PER_ROW && (
            <Tooltip>
              <TooltipTrigger
                render={
                  <span className="text-[11px] text-muted-foreground tabular-nums opacity-0 transition-opacity group-hover/space:opacity-100">
                    +{people.length - FACES_PER_ROW}
                  </span>
                }
              />
              <TooltipContent side="top">
                {people
                  .slice(FACES_PER_ROW)
                  .map((person) => userDisplayName(person))
                  .join(", ")}
              </TooltipContent>
            </Tooltip>
          )}
        </span>
      )}
      {personal ? <div className="size-6" /> : <StarToggle channel={channel} />}
    </Link>
  );
}

function SpaceList({ channels }: { channels: Channel[] }) {
  return (
    <div className="flex flex-col gap-px">
      {channels.map((channel) => (
        <SpaceRow key={channel.id} channel={channel} />
      ))}
    </div>
  );
}

function SectionLabel({
  children,
  count,
}: {
  children: string;
  count: number;
}) {
  return (
    <div className="mb-1 flex items-baseline gap-2 px-2">
      <Text
        size="xxs"
        weight="semibold"
        className="text-foreground/70 uppercase tracking-wider"
      >
        {children}
      </Text>
      <Text size="xxs" variant="muted">
        {count}
      </Text>
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
    const personal = shown.filter((c) => c.channelType === "personal");
    return {
      // #me leads, as it does in the Work column: it is the one space that is
      // yours rather than one you chose to follow.
      starred: [
        ...personal,
        ...shown.filter((c) => c.starred && c.channelType !== "personal"),
      ],
      rest: shown.filter((c) => !c.starred && c.channelType !== "personal"),
    };
  }, [channels, needle]);
  const noMatches = starred.length === 0 && rest.length === 0;

  // The title goes into the shell's own header bar, so this page wears the
  // typography and inset every other screen does rather than a heading of its
  // own invention.
  useSetHeaderContent(
    useMemo(
      () => (
        <>
          <div className="flex min-w-0 items-center gap-1.5 pl-5">
            <span className="shrink-0 text-muted-foreground">
              <SpacesIcon size={14} />
            </span>
            <span className="min-w-0 truncate font-medium text-[13px]">
              Spaces
            </span>
          </div>
          <Button
            variant="primary"
            size="sm"
            onClick={() => setCreateOpen(true)}
          >
            <PlusIcon size={14} />
            New space…
          </Button>
        </>
      ),
      [],
    ),
  );

  return (
    <div className="flex h-full min-h-0 flex-col bg-gray-1">
      <div className="scroll-mask-4 min-h-0 flex-1 overflow-auto">
        <div className="mx-auto w-full max-w-5xl px-6 py-5">
          <InputGroup className="mb-5 max-w-xs">
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
            <div className="flex flex-col gap-px">
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <Skeleton key={i} className="h-8 w-full" />
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
            <div className="flex flex-col gap-5">
              {starred.length > 0 && (
                <div>
                  <SectionLabel count={starred.length}>Starred</SectionLabel>
                  <SpaceList channels={starred} />
                </div>
              )}
              {rest.length > 0 && (
                <div>
                  {starred.length > 0 && (
                    <SectionLabel count={rest.length}>
                      Everything else
                    </SectionLabel>
                  )}
                  <SpaceList channels={rest} />
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      <CreateChannelModal open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}
