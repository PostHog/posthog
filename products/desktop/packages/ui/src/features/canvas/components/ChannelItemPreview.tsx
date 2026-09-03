import { ChatCircleIcon } from "@phosphor-icons/react";
import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import {
  Avatar,
  AvatarFallback,
  cn,
  Item,
  ItemActions,
  ItemContent,
  ItemGroup,
  ItemSeparator,
  ItemTitle,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import { formatAbsoluteDateTime, formatRelativeAge } from "@posthog/shared";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import {
  TaskRowMenuList,
  type TaskRowMenuProps,
} from "@posthog/ui/features/canvas/components/TaskRowMenu";
import { channelItemAuthor } from "@posthog/ui/features/canvas/hooks/useChannelItemFacts";
import { useChannelTaskStatus } from "@posthog/ui/features/canvas/hooks/useChannelTaskStatus";
import { useLatestTurnMessage } from "@posthog/ui/features/canvas/hooks/useLatestTurnMessage";
import { getOriginProductMeta } from "@posthog/ui/features/sidebar/components/items/TaskIcon";
import { TaskDotMark } from "@posthog/ui/features/sidebar/components/items/TaskStatusDot";
import {
  type TaskBadge,
  type TaskDot,
  TONE_ICON_VAR,
  taskBadges,
  taskDot,
} from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { CopyButton } from "@posthog/ui/primitives/CopyButton";
import { FactLabel, FactList } from "@posthog/ui/primitives/FactList";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { type ReactNode, useEffect } from "react";

/** Matches the rows' own tooltip delay, so the card doesn't feel slower. */
const TOOLTIP_DELAY_MS = 200;

/** What the card is about: the row that is being pointed at. */
export interface ChannelItemPreviewPayload {
  item: ChannelItemModel;
  menu: TaskRowMenuProps;
}

/**
 * The mark the row it came from leads with, which the card wears beside the
 * title rather than in a gutter of its own.
 *
 * A session's mark is its state dot rather than a generic chat glyph, which
 * said nothing the title didn't. A canvas has no run behind it and keeps its
 * template glyph in canvas violet; a session with no run to read falls back to
 * the chat glyph rather than inventing a state.
 */
function previewGlyph(item: ChannelItemModel, dot: TaskDot | null): ReactNode {
  if (item.kind === "canvas") {
    // Matches the schema's own default for boards saved before templating.
    return iconForTemplate(item.templateId ?? "freeform", {
      size: 15,
      className: "text-violet-9",
    });
  }
  if (!dot) return <ChatCircleIcon size={15} className="text-gray-10" />;
  return <TaskDotMark dot={dot} />;
}

/**
 * Who made it, as the avatar alone. The name is worth a line of the card only
 * where the avatar can't carry it, so it goes to the label and a tooltip
 * instead of a row of its own.
 */
function AuthorAvatar({ item }: { item: ChannelItemModel }) {
  const author = channelItemAuthor(item);
  if (!author) return null;
  const label = `Created by ${author}`;
  return (
    <TooltipProvider delay={TOOLTIP_DELAY_MS}>
      {/* `disableHoverablePopup` and `pointer-events-none` for the reason the
          rows' tooltips take them: a popup the pointer can hold open sits over
          the card and swallows what is under it. */}
      <Tooltip disableHoverablePopup>
        <TooltipTrigger
          render={
            // `role="img"` for the same reason the row's badges take one: the
            // avatar is a fact about the item, and it needs a name a screen
            // reader can read.
            // `flex`: quill's avatar is an inline-flex box, so an inline
            // wrapper carries the line box's descender space with it and the
            // avatar sits high in a taller container.
            <span aria-label={label} role="img" className="flex shrink-0">
              {item.authorUser ? (
                <UserAvatar size="xs" user={item.authorUser} />
              ) : (
                <Avatar size="xs">
                  <AvatarFallback>
                    {author.charAt(0).toUpperCase()}
                  </AvatarFallback>
                </Avatar>
              )}
            </span>
          }
        />
        <TooltipContent side="top" className="pointer-events-none select-none">
          {label}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

/**
 * One of the row's badges. A badge that points somewhere — a PR — is a button
 * that opens it, which the row itself can't offer: a row is a `<button>`, so its
 * badges have to stay spans. The card is the surface where they can be clicked.
 */
function Badge({ badge: { Icon, label, tone, url } }: { badge: TaskBadge }) {
  const glyph = (
    // An explicit `color` (an SVG fill) rather than a text-* class, the same way
    // the row's badges are drawn.
    <Icon
      aria-hidden
      size={11}
      weight={tone ? "fill" : "regular"}
      color={tone ? TONE_ICON_VAR[tone] : undefined}
    />
  );
  const className = "flex items-center gap-1 text-muted-foreground text-xs";
  if (!url) {
    return (
      <span className={className}>
        {glyph}
        {label}
      </span>
    );
  }
  return (
    <button
      type="button"
      title={url}
      className={cn(
        className,
        // Underlined at rest, dotted, so the badge that can be clicked is
        // marked as such without shouting over the badges that can't.
        "cursor-pointer rounded-xs underline decoration-dotted underline-offset-2 hover:text-foreground hover:decoration-solid focus-visible:outline-2 focus-visible:outline-ring",
      )}
      onClick={() => openExternalUrl(url)}
    >
      {glyph}
      {label}
    </button>
  );
}

/**
 * The branch's value cell: the name, and the one thing a reader wants from a
 * branch name — it, in their clipboard. Truncated rather than wrapped, because
 * the button has to stay at the end of the line.
 */
function BranchLine({ branch }: { branch: string }) {
  return (
    <span className="flex min-w-0 items-center gap-1">
      <span className="truncate" title={branch}>
        {branch}
      </span>
      <CopyButton
        bare
        confirm="tooltip"
        text={branch}
        label="Copy branch name"
      />
    </span>
  );
}

/**
 * What the card can state plainly: where the session's work sits, when it last
 * moved, who filed it, and what it wants. Facts a reader looks up belong in one
 * column rather than scattered between a badge row and a sentence.
 */
function ItemFacts({
  item,
  source,
  status,
}: {
  item: ChannelItemModel;
  /** The origin badge, relabeled: the row's column already says "Source". */
  source: TaskBadge | undefined;
  /** The PR's state, which is what a reader means by a session's status here. */
  status: TaskBadge | undefined;
}) {
  const repository = item.repository?.label;
  return (
    <FactList>
      {repository && (
        <>
          <FactLabel>Repo</FactLabel>
          <span className="truncate" title={repository}>
            {repository}
          </span>
        </>
      )}
      {item.branch && (
        <>
          <FactLabel>Branch</FactLabel>
          <BranchLine branch={item.branch} />
        </>
      )}
      <FactLabel>Updated</FactLabel>
      {/* The exact moment behind the phrase, the same way a row carries it. */}
      <span title={formatAbsoluteDateTime(item.ts)}>
        {formatRelativeAge(item.ts)}
      </span>
      {source && (
        <>
          <FactLabel>Source</FactLabel>
          {/* Still a badge, because Slack's is a link back to the thread. */}
          <Badge badge={source} />
        </>
      )}
      {status && (
        <>
          <FactLabel>Status</FactLabel>
          {/* Still a badge: the PR's state carries its colour, and it opens. */}
          <Badge badge={status} />
        </>
      )}
    </FactList>
  );
}

/**
 * What the row's marks mean, in words: the dot's own label, the last thing the
 * agent said, then the badges'.
 *
 * The card is where the sidebar's vocabulary gets spelled out, so it says
 * exactly what the row says rather than a second opinion — it used to show the
 * run's raw status ("Ready", "In progress"), a scale the rows stopped using
 * when the dot took over, so a quiet row could sit under a green "Ready" badge
 * and a working one under nothing at all.
 *
 * Laid out as the same `Item` as the header above it, and like it carries no
 * gutter: the dot the state belongs to is already up beside the title, and
 * drawing it twice would make one state look like two.
 */
function ItemSignals({
  dot,
  badges,
  message,
}: {
  dot: TaskDot | null;
  badges: TaskBadge[];
  message: string | null;
}) {
  // A canvas has no state, nothing said and nothing to link: the separator
  // alone would promise a block that isn't there.
  if (!dot && badges.length === 0 && !message) return null;
  return (
    <>
      <ItemSeparator className="my-0" />
      {/* `flex-nowrap`: quill's `Item` wraps, and a message with a url in it has
          a min-content wider than the card, which dropped this column onto a
          line of its own and out past the card's edge. */}
      <Item size="xs" className="flex-nowrap items-start p-2">
        <ItemContent className="min-w-0 gap-1.5">
          {/* What the row's dot says, in words. Above the message, like the
              badges: the agent's own words are the longest thing here, so
              anything under them reads as part of the transcript. */}
          {dot && <span className="text-xs">{dot.label}</span>}
          {badges.length > 0 && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              {badges.map((badge) => (
                <Badge key={badge.key} badge={badge} />
              ))}
            </div>
          )}
          {message && (
            // Three lines: enough for the agent's closing sentence, short of
            // turning the card into a transcript you have to read.
            <p className="line-clamp-3 break-words text-muted-foreground text-xs leading-snug">
              {message}
            </p>
          )}
        </ItemContent>
      </Item>
    </>
  );
}

/**
 * The contents of a row's hover card: what the thing is, what its marks mean,
 * the last thing the agent said, who made it, and what you can do to it.
 *
 * Rendered by the one card the list shares, from the payload of whichever
 * trigger is active — so the hooks in here run for the row being pointed at,
 * once, rather than once per row in the list.
 */
export function ChannelItemPreview({
  payload,
  onAction,
  onSubmenuOpenChange,
}: {
  payload: ChannelItemPreviewPayload;
  onAction: () => void;
  onSubmenuOpenChange: (open: boolean) => void;
}) {
  const { item, menu } = payload;
  // The submenu flag lives on the provider, and Base UI reports no close when
  // the menu goes away with its card. Lower it here, so a card left with
  // "File to…" open cannot pin the shared popup open behind it.
  useEffect(() => () => onSubmenuOpenChange(false), [onSubmenuOpenChange]);
  // The PR lookup runs here even where the row skipped it (the space tree does,
  // to stay off the host): a hover is one row at a time and a deliberate ask,
  // and the card is the surface that should be able to say "merged".
  const status = useChannelTaskStatus(item);
  const message = useLatestTurnMessage(item.task);
  const dot = status ? taskDot(status) : null;
  const badges = status ? taskBadges(status) : [];
  // The origin moves up into the facts, where a labeled column already says
  // what it is; the badge keeps its glyph and its link.
  const origin = badges.find((badge) => badge.key === "origin");
  const originMeta = getOriginProductMeta(status?.originProduct);
  const source =
    origin && originMeta ? { ...origin, label: originMeta.label } : undefined;
  // The PR's state is what "status" means in a labeled column; the dot's own
  // wording is about the session and stays with the agent's words below.
  const pullRequest = badges.find((badge) => badge.key === "pr");

  return (
    <ItemGroup className="gap-0!">
      <Item size="xs" className="flex-nowrap p-2">
        <ItemContent className="min-w-0 gap-2">
          <ItemTitle className="wrap-break-word flex items-start gap-2">
            <span className="flex h-[1lh] w-4 shrink-0 items-center justify-center">
              {previewGlyph(item, dot)}
            </span>
            <span className="min-w-0 font-bold">{item.title}</span>
          </ItemTitle>
          <div className="pl-6">
            <ItemFacts item={item} source={source} status={pullRequest} />
          </div>
        </ItemContent>
        <ItemActions className="self-start">
          <AuthorAvatar item={item} />
        </ItemActions>
      </Item>
      <ItemSignals
        dot={dot}
        badges={badges.filter(
          (badge) => badge !== origin && badge !== pullRequest,
        )}
        message={message}
      />
      <ItemSeparator className="my-0" />
      <div className="p-1">
        <TaskRowMenuList
          menu={menu}
          onAction={onAction}
          onSubmenuOpenChange={onSubmenuOpenChange}
        />
      </div>
    </ItemGroup>
  );
}
