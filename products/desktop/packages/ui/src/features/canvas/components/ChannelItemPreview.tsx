import { ChatCircleIcon } from "@phosphor-icons/react";
import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import {
  Avatar,
  AvatarFallback,
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemMedia,
  ItemSeparator,
  ItemTitle,
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
import { TaskDotMark } from "@posthog/ui/features/sidebar/components/items/TaskStatusDot";
import {
  TONE_ICON_VAR,
  taskBadges,
  taskDot,
} from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import type { ReactNode } from "react";

/** What the card is about: the row that is being pointed at. */
export interface ChannelItemPreviewPayload {
  item: ChannelItemModel;
  menu: TaskRowMenuProps;
}

/**
 * What the card leads with. A canvas gets its template glyph in canvas violet; a
 * task gets the chat glyph the sidebar uses for a task with nothing going on —
 * before this, a task was shown wearing a canvas's icon.
 */
function previewGlyph(item: ChannelItemModel): ReactNode {
  if (item.kind !== "canvas") {
    return <ChatCircleIcon size={15} className="text-gray-10" />;
  }
  // Matches the schema's own default for boards saved before templating.
  return iconForTemplate(item.templateId ?? "freeform", {
    size: 15,
    className: "text-violet-9",
  });
}

function authorLabel(item: ChannelItemModel): string | null {
  if (item.authorUser) return userDisplayName(item.authorUser);
  return item.authorName;
}

/**
 * Who made it, as the avatar alone. The name is worth a line of the card only
 * where the avatar can't carry it, so it goes to the label and the title
 * attribute instead of a row of its own.
 */
function AuthorAvatar({ item }: { item: ChannelItemModel }) {
  const author = authorLabel(item);
  if (!author) return null;
  const label = `Created by ${author}`;
  return (
    // `role="img"` for the same reason the row's badges take one: the avatar is
    // a fact about the item, and it needs a name a screen reader can read.
    <span aria-label={label} role="img" title={label}>
      {item.authorUser ? (
        <UserAvatar size="xs" user={item.authorUser} />
      ) : (
        <Avatar size="xs">
          <AvatarFallback>{author.charAt(0).toUpperCase()}</AvatarFallback>
        </Avatar>
      )}
    </span>
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
 * Laid out as an `Item` like the header above it, which is what puts the dot in
 * the same gutter as the card's glyph and starts every line of this section in
 * the same column as the title.
 */
function ItemSignals({ item }: { item: ChannelItemModel }) {
  // The PR lookup runs here even where the row skipped it (the space tree does,
  // to stay off the host): a hover is one row at a time and a deliberate ask,
  // and the card is the surface that should be able to say "merged".
  const status = useChannelTaskStatus(item);
  const message = useLatestTurnMessage(item.task);
  if (!status) return null;
  const dot = taskDot(status);
  const badges = taskBadges(status);

  return (
    <>
      <ItemSeparator className="my-0" />
      <Item size="xs" className="items-start p-2">
        <ItemMedia variant="icon" className="size-5">
          <TaskDotMark dot={dot} />
        </ItemMedia>
        <ItemContent className="gap-1.5">
          <span className="text-xs">{dot.label}</span>
          {message && (
            // Three lines: enough for the agent's closing sentence, short of
            // turning the card into a transcript you have to read.
            <p className="line-clamp-3 text-muted-foreground text-xs leading-snug">
              {message}
            </p>
          )}
          {badges.length > 0 && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              {badges.map(({ key, Icon, label, tone }) => (
                <span
                  key={key}
                  className="flex items-center gap-1 text-muted-foreground text-xs"
                >
                  {/* An explicit `color` (an SVG fill) rather than a text-*
                      class, the same way the row's badges are drawn. */}
                  <Icon
                    aria-hidden
                    size={11}
                    weight={tone ? "fill" : "regular"}
                    color={tone ? TONE_ICON_VAR[tone] : undefined}
                  />
                  {label}
                </span>
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

  return (
    <ItemGroup className="gap-0!">
      <Item size="xs" className="p-2">
        <ItemMedia variant="icon" className="size-5">
          {previewGlyph(item)}
        </ItemMedia>
        <ItemContent>
          <ItemTitle>{item.title}</ItemTitle>
          <ItemDescription>
            {item.kind === "canvas" ? "Canvas" : "Task"} · updated{" "}
            {formatRelativeTimeShort(item.ts)}
          </ItemDescription>
        </ItemContent>
        {/* Who made it rides on the identity row rather than taking a row of
            its own — the card is a glance, and a line of chrome for a name is
            a line the agent's own words could have had. */}
        <ItemActions>
          <AuthorAvatar item={item} />
        </ItemActions>
      </Item>
      <ItemSignals item={item} />
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
