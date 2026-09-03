import { CrownSimpleIcon, GitBranchIcon } from "@phosphor-icons/react";
import {
  AvatarGroup,
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemSeparator,
  ItemTitle,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import type { UserBasic } from "@posthog/shared/domain-types";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import {
  type ChannelActionItem,
  ChannelActionList,
} from "@posthog/ui/features/canvas/components/channelActions";
import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useSpaceOverview } from "@posthog/ui/features/canvas/hooks/useRecentSpaceTasks";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { DOT_TONE_VAR } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";

/** What the card is about: the space that is being pointed at. */
export interface SpacePreviewPayload {
  channel: Channel;
  /** Sessions inside with something unread, as the row already counted them. */
  unreadSessions: number;
  /** Sessions inside waiting on an answer from you. */
  blockedSessions: number;
  actions: ChannelActionItem[];
}

/** Matches the rows' own tooltip delay, so the card doesn't feel slower. */
const TOOLTIP_DELAY_MS = 200;

/**
 * How many faces the group shows. Past this the stack stops reading as people
 * and starts reading as texture, and the card is a glance.
 */
const MAX_PEOPLE = 5;

/** Repos past this are counted rather than named — the card has one line. */
const MAX_REPOS = 3;

/**
 * One person in the space, as their avatar. The creator wears a crown, because
 * "who made this" is the one thing about a space's people the space itself
 * knows — everyone else in the stack is there for having run something lately.
 */
function Person({ user, isCreator }: { user: UserBasic; isCreator: boolean }) {
  const name = userDisplayName(user);
  const label = isCreator ? `${name} created this space` : name;
  return (
    <Tooltip disableHoverablePopup>
      <TooltipTrigger
        render={
          // `flex`, not `block`: quill's avatar is an inline-flex box, so a
          // block wrapper adds the line box's descender space under it and the
          // avatar rides at the top of a taller container — enough to knock one
          // face out of line with its neighbours.
          <span
            aria-label={label}
            role="img"
            className="relative flex shrink-0"
          >
            <UserAvatar size="xs" user={user} />
            {isCreator && (
              // Top-left rather than top-right: the stack tucks each face
              // behind the one after it, so the creator's right corner is
              // under its neighbour and a crown there is a sliver of gold
              // nobody can read. Its left corner is the one nothing covers.
              <span className="-top-1 -left-1 absolute rounded-full bg-background p-px">
                <CrownSimpleIcon
                  size={9}
                  weight="fill"
                  className="block text-primary"
                />
              </span>
            )}
          </span>
        }
      />
      <TooltipContent side="top" className="pointer-events-none select-none">
        {label}
      </TooltipContent>
    </Tooltip>
  );
}

/**
 * The space's people, stacked so each face tucks behind the one after it —
 * which is what `reverse` gives, and why the creator's crown sits on the left
 * corner of its avatar rather than the right.
 */
function SpacePeople({
  people,
  creatorUuid,
}: {
  people: UserBasic[];
  creatorUuid: string | undefined;
}) {
  if (people.length === 0) return null;
  return (
    <TooltipProvider delay={TOOLTIP_DELAY_MS}>
      <AvatarGroup stacked reverse size="xs">
        {people.map((user) => (
          <Person
            key={user.uuid}
            user={user}
            isCreator={user.uuid === creatorUuid}
          />
        ))}
      </AvatarGroup>
    </TooltipProvider>
  );
}

/** A counted signal, drawn as the dot the row shows for it plus the words. */
function CountSignal({
  count,
  tone,
  label,
}: {
  count: number;
  tone: "blocked" | "attention";
  label: string;
}) {
  if (count === 0) return null;
  return (
    <span className="flex items-center gap-1 text-muted-foreground text-xs">
      <span
        aria-hidden
        className="size-2 shrink-0 rounded-full"
        style={{
          backgroundColor:
            tone === "blocked" ? DOT_TONE_VAR.blue : "var(--primary)",
        }}
      />
      {count} {label}
    </span>
  );
}

/**
 * What the space is asking of you and what it is wired to.
 *
 * Only what it has to say: a space with nothing owed and no repos gets no
 * section at all rather than a line telling it so. "All caught up" is the
 * sessions' own vocabulary, and a space is not a session.
 */
function SpaceSignals({
  unreadSessions,
  blockedSessions,
  repositories,
}: {
  unreadSessions: number;
  blockedSessions: number;
  repositories: string[];
}) {
  const shown = repositories.slice(0, MAX_REPOS);
  const rest = repositories.length - shown.length;
  const hasCounts = blockedSessions > 0 || unreadSessions > 0;
  if (!hasCounts && shown.length === 0) return null;
  return (
    <>
      <ItemSeparator className="my-0" />
      <Item size="xs" className="flex-nowrap items-start p-2">
        <ItemContent className="min-w-0 gap-1.5">
          {hasCounts && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              {/* Blue first, the way the row's pair is ordered: the sessions
                  you can clear from here come before the ones to read. */}
              <CountSignal
                count={blockedSessions}
                tone="blocked"
                label="waiting on you"
              />
              <CountSignal
                count={unreadSessions}
                tone="attention"
                label="unread"
              />
            </div>
          )}
          {shown.length > 0 && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              {shown.map((repo) => (
                <span
                  key={repo}
                  className="flex min-w-0 items-center gap-1 text-muted-foreground text-xs"
                >
                  <GitBranchIcon aria-hidden size={11} className="shrink-0" />
                  <span className="truncate">{repo}</span>
                </span>
              ))}
              {rest > 0 && (
                <span className="text-muted-foreground text-xs">
                  +{rest} more
                </span>
              )}
            </div>
          )}
        </ItemContent>
      </Item>
    </>
  );
}

/**
 * The card itself, given everything it draws. Split from the hook below so it
 * can be rendered from a story: the space's people come from a query, and a
 * query resolves to nothing in Storybook.
 */
export function SpacePreviewContent({
  payload,
  people,
  total,
  onAction,
}: {
  payload: SpacePreviewPayload;
  people: UserBasic[];
  /** Sessions in the space, or `null` while the page hasn't arrived. */
  total: number | null;
  onAction: () => void;
}) {
  const { channel, unreadSessions, blockedSessions, actions } = payload;
  const hasAttention = unreadSessions > 0 || blockedSessions > 0;

  return (
    <ItemGroup className="gap-0!">
      <Item size="xs" className="flex-nowrap p-2">
        <ItemContent className="min-w-0">
          {/* The row's own mark rides with the name rather than in a gutter of
              its own: a quiet space has no mark, and a column that is empty on
              most cards is an indent nothing pays for. */}
          <ItemTitle className="flex items-center gap-2 break-words">
            {hasAttention && (
              <span
                aria-hidden
                className="size-2 shrink-0 rounded-full"
                style={{
                  backgroundColor:
                    blockedSessions > 0 ? DOT_TONE_VAR.blue : "var(--primary)",
                }}
              />
            )}
            {channel.name}
          </ItemTitle>
          <ItemDescription>
            {/* No count until the page lands: "0 sessions" on a space that has
                them is a wrong answer, and the card is about to have a right
                one. */}
            {total == null
              ? "Space"
              : `Space \u00b7 ${total} ${total === 1 ? "session" : "sessions"}`}
          </ItemDescription>
        </ItemContent>
        {/* Top-aligned: the people belong to the space's name, not to the
            block of text under it. */}
        <ItemActions className="self-start">
          <SpacePeople people={people} creatorUuid={channel.createdBy?.uuid} />
        </ItemActions>
      </Item>
      <SpaceSignals
        unreadSessions={unreadSessions}
        blockedSessions={blockedSessions}
        repositories={channel.repositories}
      />
      <ItemSeparator className="my-0" />
      <div className="p-1">
        <ChannelActionList actions={actions} onAction={onAction} />
      </div>
    </ItemGroup>
  );
}

/**
 * The contents of a space row's hover card: what the space is, who has been
 * working in it, what it's wired to, and what you can do to it.
 *
 * Rendered by the one card the sidebar shares, from the payload of whichever
 * trigger is active — so the query behind the people runs for the space being
 * pointed at, once, rather than once per space in the list.
 */
export function SpacePreview({
  payload,
  onAction,
}: {
  payload: SpacePreviewPayload;
  onAction: () => void;
}) {
  const overview = useSpaceOverview(
    payload.channel.id,
    payload.channel.createdBy,
    MAX_PEOPLE,
  );
  return (
    <SpacePreviewContent
      payload={payload}
      people={overview.people}
      total={overview.total}
      onAction={onAction}
    />
  );
}
