import { ChatCircleIcon } from "@phosphor-icons/react";
import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import { deriveHeadline } from "@posthog/core/inbox/reportPresentation";
import {
  Avatar,
  AvatarFallback,
  cn,
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
import { formatRelativeTimeShort } from "@posthog/shared";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import {
  TaskRowMenuList,
  type TaskRowMenuProps,
} from "@posthog/ui/features/canvas/components/TaskRowMenu";
import { useChannelTaskStatus } from "@posthog/ui/features/canvas/hooks/useChannelTaskStatus";
import { useLatestTurnMessage } from "@posthog/ui/features/canvas/hooks/useLatestTurnMessage";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { getOriginProductMeta } from "@posthog/ui/features/sidebar/components/items/TaskIcon";
import { TaskDotMark } from "@posthog/ui/features/sidebar/components/items/TaskStatusDot";
import {
  type TaskBadge,
  type TaskDot,
  TONE_ICON_VAR,
  taskBadges,
  taskDot,
} from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
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

function authorLabel(item: ChannelItemModel): string | null {
  if (item.authorUser) return userDisplayName(item.authorUser);
  return item.authorName;
}

/**
 * Who made it, as the avatar alone. The name is worth a line of the card only
 * where the avatar can't carry it, so it goes to the label and a tooltip
 * instead of a row of its own.
 */
function AuthorAvatar({ item }: { item: ChannelItemModel }) {
  const author = authorLabel(item);
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
  dot: TaskDot;
  badges: TaskBadge[];
  message: string | null;
}) {
  return (
    <>
      <ItemSeparator className="my-0" />
      {/* `flex-nowrap`: quill's `Item` wraps, and a message with a url in it has
          a min-content wider than the card, which dropped this column onto a
          line of its own and out past the card's edge. */}
      <Item size="xs" className="flex-nowrap items-start p-2">
        <ItemContent className="min-w-0 gap-1.5">
          <span className="text-xs">{dot.label}</span>
          {message && (
            // Three lines: enough for the agent's closing sentence, short of
            // turning the card into a transcript you have to read.
            <p className="line-clamp-3 break-words text-muted-foreground text-xs leading-snug">
              {message}
            </p>
          )}
          {badges.length > 0 && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              {badges.map((badge) => (
                <Badge key={badge.key} badge={badge} />
              ))}
            </div>
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
  const source = getOriginProductMeta(item.source ?? undefined);
  const canvasSummary =
    item.kind === "canvas" ? deriveHeadline(item.description) : null;

  return (
    <ItemGroup className="gap-0!">
      <Item size="xs" className="flex-nowrap p-2">
        <ItemContent className="min-w-0">
          {/* No gutter: the mark is one glyph on one line, and a column for it
              indents everything under it for the whole height of the card. */}
          <ItemTitle className="flex items-baseline gap-2 break-words">
            <span className="flex size-4 shrink-0 translate-y-0.5 items-center justify-center">
              {previewGlyph(item, dot)}
            </span>
            <span className="min-w-0">{item.title}</span>
          </ItemTitle>
          <ItemDescription>
            {item.kind === "canvas" ? "Canvas" : "Task"}
            {source ? ` from ${source.label}` : ""} · updated{" "}
            {formatRelativeTimeShort(item.ts)}
          </ItemDescription>
          {canvasSummary ? (
            <p className="line-clamp-3 break-words text-muted-foreground text-xs leading-snug">
              {canvasSummary}
            </p>
          ) : null}
        </ItemContent>
        {/* Who made it rides on the identity row rather than taking a row of
            its own — the card is a glance, and a line of chrome for a name is
            a line the agent's own words could have had. Top-aligned: it belongs
            to the title, not to the block of text under it. */}
        <ItemActions className="self-start">
          <AuthorAvatar item={item} />
        </ItemActions>
      </Item>
      {dot && status && (
        <ItemSignals dot={dot} badges={taskBadges(status)} message={message} />
      )}
      {/* The row's actions live here now: a row at rest shows its status, and
          the card is already the surface you're pointing at when you want to do
          something to it. */}
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
