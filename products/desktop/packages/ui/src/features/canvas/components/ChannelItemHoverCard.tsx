import { PreviewCard } from "@base-ui/react/preview-card";
import { ChatCircleIcon } from "@phosphor-icons/react";
import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import {
  runStatusLabel,
  runStatusVariant,
} from "@posthog/core/canvas/runStatus";
import {
  Avatar,
  AvatarFallback,
  Badge,
  Card,
  Item,
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
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { type ReactNode, useCallback, useEffect, useState } from "react";

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
 * How long the keyboard has to rest on a row before its card opens. Long enough
 * that arrowing through the list doesn't flash a card on every row it passes.
 */
const KEYBOARD_OPEN_DELAY_MS = 350;

/**
 * The row's hover card: what the thing is, who made it, and what you can do to
 * it. Shared by the channel sidebar's rows and the space tree's session rows so
 * the two can't drift into showing different facts or actions for one task.
 *
 * `children` is the row itself, handed to the trigger.
 */
export function ChannelItemHoverCard({
  item,
  menu,
  highlighted = false,
  children,
}: {
  item: ChannelItemModel;
  menu: TaskRowMenuProps;
  /** The keyboard is on this row, which opens the card as hovering does. */
  highlighted?: boolean;
  children: ReactNode;
}) {
  const [cardOpen, setCardOpen] = useState(false);
  const [submenuOpen, setSubmenuOpen] = useState(false);
  const [keyboardOpen, setKeyboardOpen] = useState(false);
  // Stable: `TaskRowMenuList` builds its item components from these, so a new
  // identity each render would remount every button in the card.
  const closeCard = useCallback(() => setCardOpen(false), []);
  const statusLabel = runStatusLabel(item.rawStatus);
  const author = authorLabel(item);

  // Closing is immediate: once the highlight has moved, a card still open
  // points at the wrong row.
  useEffect(() => {
    if (!highlighted) {
      setKeyboardOpen(false);
      return;
    }
    const timer = setTimeout(
      () => setKeyboardOpen(true),
      KEYBOARD_OPEN_DELAY_MS,
    );
    return () => clearTimeout(timer);
  }, [highlighted]);

  return (
    // Controlled so the card survives its own submenu: "File to…" opens in a
    // portal outside the card, and the pointer moving there reads as leaving the
    // card, which would take the menu down with it.
    <PreviewCard.Root
      open={cardOpen || submenuOpen || keyboardOpen}
      onOpenChange={setCardOpen}
    >
      <PreviewCard.Trigger
        delay={400}
        closeDelay={100}
        render={<div className="min-w-0">{children}</div>}
      />
      <PreviewCard.Portal>
        <PreviewCard.Positioner
          side="right"
          align="start"
          sideOffset={10}
          className="z-50"
        >
          {/* The card is quill's `Card` and `Item` parts throughout — the popup
              itself carries no surface styling, so this window's hover card
              matches every other card in the app rather than a hand-tuned
              shadow of its own. The card's own padding is off (`gap-0 py-0`):
              each section pays for its own inset, which is what lets the rules
              run edge to edge and the action rows highlight full width. */}
          <PreviewCard.Popup
            render={
              <Card
                size="sm"
                className="w-64 gap-0 border border-border py-0 shadow-md"
              />
            }
          >
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
              </Item>
              {statusLabel && (
                <div className="px-2 pb-2">
                  <Badge variant={runStatusVariant(item.rawStatus)}>
                    {statusLabel}
                  </Badge>
                </div>
              )}
              {author && (
                <>
                  {/* Every section of the card gets the rule above it, canvases
                      included — the author is a different fact from the thing's
                      identity whether or not there are actions under it. */}
                  <ItemSeparator className="my-0" />
                  <Item size="xs" className="p-2">
                    <ItemMedia variant="icon">
                      {item.authorUser ? (
                        <UserAvatar size="xs" user={item.authorUser} />
                      ) : (
                        <Avatar size="xs">
                          <AvatarFallback>
                            {author.charAt(0).toUpperCase()}
                          </AvatarFallback>
                        </Avatar>
                      )}
                    </ItemMedia>
                    <ItemContent className="gap-0">
                      <ItemTitle>{author}</ItemTitle>
                      <ItemDescription>Created by</ItemDescription>
                    </ItemContent>
                  </Item>
                </>
              )}
              {/* The row's actions live here now: a row at rest shows its
                  status, and the card is already the surface you're pointing at
                  when you want to do something to it. */}
              <ItemSeparator className="my-0" />
              <div className="p-1">
                <TaskRowMenuList
                  menu={menu}
                  onAction={closeCard}
                  onSubmenuOpenChange={setSubmenuOpen}
                />
              </div>
            </ItemGroup>
          </PreviewCard.Popup>
        </PreviewCard.Positioner>
      </PreviewCard.Portal>
    </PreviewCard.Root>
  );
}
