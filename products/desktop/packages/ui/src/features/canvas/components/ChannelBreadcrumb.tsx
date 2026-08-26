import { LinkIcon, StarIcon } from "@phosphor-icons/react";
import {
  Button,
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
  cn,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import { useChannelStarMutations } from "@posthog/ui/features/canvas/hooks/useChannelStars";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { copyChannelLink } from "@posthog/ui/features/canvas/utils/copyChannelLink";
import { HeaderTitleEditor } from "@posthog/ui/features/task-detail/HeaderTitleEditor";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { Flex, Text } from "@radix-ui/themes";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { type ReactNode, useState } from "react";

interface ChannelBreadcrumbProps {
  /** The channel (root) segment label. */
  channelName: string;
  /**
   * When provided, the "# channel" segment links to the channel home, like the
   * sidebar channel row and the channel-view header.
   */
  channelId?: string;
  /**
   * An optional segment between the space and the leaf — the section a scene
   * belongs to, e.g. "{space} / Loops / {loop}". `onClick` links it; without
   * one it reads as a plain step.
   */
  middle?: { icon?: ReactNode; label: string; onClick?: () => void };
  /** Optional leading icon for the leaf segment (e.g. a canvas's tier icon). */
  leafIcon?: ReactNode;
  /**
   * The trailing (current page) segment label. Omitted at a space's root, which
   * renders the channel segment alone — same size and styling either way.
   */
  leafLabel?: string;
  editScopeKey?: string;
  /**
   * When provided, the leaf becomes inline-editable: click to rename, Enter or
   * blur to submit, Escape to cancel. Receives the trimmed new value.
   */
  onRename?: (next: string) => void;
  /** Right-aligned slot pushed to the far end of the bar (e.g. an opener). */
  trailing?: ReactNode;
  /**
   * Slot that rides directly after the leaf segment instead of the far end —
   * for controls that act on the leaf itself (copy its link), which read as
   * unrelated once the bar's width separates them from the name.
   */
  leafTrailing?: ReactNode;
}

// "# channel / leaf" header breadcrumb shared across channel scenes (CONTEXT.md,
// new + existing tasks, canvases). The leaf can carry a tier icon and, when
// onRename is given, edits inline on a single click using the same editor as
// task titles. When channelId is given, the "# channel" segment links back to
// the channel home.
export function ChannelBreadcrumb({
  channelName,
  channelId,
  middle,
  leafIcon,
  leafLabel,
  editScopeKey,
  onRename,
  trailing,
  leafTrailing,
}: ChannelBreadcrumbProps) {
  const spacesLayout = useChannelsLayout();
  // Only a leaf is renamable, so the scope key falls back to its label.
  const currentEditScope = editScopeKey ?? leafLabel ?? "";
  const [editingScope, setEditingScope] = useState<string | null>(null);
  const editing = editingScope === currentEditScope;
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const atChannelHome = channelId ? pathname === `/spaces/${channelId}` : false;

  const channelSegment = (
    <BreadcrumbSegment
      icon={channelGlyph(channelName, {
        size: 12,
        space: spacesLayout,
        className: "shrink-0 text-muted-foreground/80",
      })}
      label={channelName}
      strong
      onClick={
        channelId && !atChannelHome
          ? () =>
              void navigate({
                to: "/spaces/$channelId",
                params: { channelId },
              })
          : undefined
      }
      contextMenu={Boolean(channelId)}
    />
  );

  return (
    <Flex align="center" justify="between" gap="2" className="w-full min-w-0">
      {/* flex-1 so the inline editor can stretch across the row; the trailing
          slot still sits at the far end. */}
      <Flex align="center" gap="0.5" className="min-w-0 flex-1">
        {channelId ? (
          <ChannelSegmentContextMenu channelId={channelId}>
            {channelSegment}
          </ChannelSegmentContextMenu>
        ) : (
          channelSegment
        )}
        {middle && (
          <>
            <BreadcrumbSeparator />
            <BreadcrumbSegment
              icon={middle.icon}
              label={middle.label}
              onClick={middle.onClick}
            />
          </>
        )}
        {leafLabel !== undefined && (
          <>
            <BreadcrumbSeparator />
            {editing && onRename ? (
              <HeaderTitleEditor
                initialTitle={leafLabel}
                onSubmit={(next) => {
                  setEditingScope(null);
                  onRename(next);
                }}
                onCancel={() => setEditingScope(null)}
                className="h-6 px-2 font-normal text-[13px]"
              />
            ) : onRename ? (
              <Tooltip>
                <TooltipTrigger render={<span className="flex min-w-0" />}>
                  <BreadcrumbSegment
                    icon={<span className="mr-0.5">{leafIcon}</span>}
                    label={leafLabel}
                    shrink
                    onClick={() => setEditingScope(currentEditScope)}
                    className="pr-1"
                  />
                </TooltipTrigger>
                <TooltipContent>{leafLabel}</TooltipContent>
              </Tooltip>
            ) : (
              <BreadcrumbSegment
                icon={leafIcon}
                label={leafLabel}
                muted
                shrink
              />
            )}
            {leafTrailing && (
              <span className="flex shrink-0 items-center">{leafTrailing}</span>
            )}
          </>
        )}
      </Flex>
      {trailing}
    </Flex>
  );
}

/**
 * One segment of the breadcrumb. Always a Button, so every segment carries the
 * same padding, height and icon gap whether or not it goes anywhere — the leaf
 * used to be bare text, which left it visually adrift from its siblings.
 *
 * Without `onClick` the segment is genuinely inert: `aria-disabled` (so quill
 * drops the hover fill and assistive tech reads it as unavailable) plus
 * `pointer-events-none`, and out of the tab order. The disabled dimming is
 * overridden — a breadcrumb has to stay readable.
 */
function BreadcrumbSegment({
  icon,
  label,
  strong,
  muted,
  shrink,
  onClick,
  contextMenu = false,
  className,
  ...rest
}: {
  icon?: ReactNode;
  label: string;
  /** The leaf gives up width first, since it carries the longest name. */
  shrink?: boolean;
  /** The root segment carries the space name, which reads heavier. */
  strong?: boolean;
  /** The leaf is the current page, so it sits back from the linked segments. */
  muted?: boolean;
  /** Navigates, or (on a renamable leaf) opens the inline editor. */
  onClick?: () => void;
  contextMenu?: boolean;
  className?: string;
}) {
  const interactive = Boolean(onClick);

  return (
    <Button
      {...rest}
      type="button"
      size="sm"
      aria-disabled={interactive ? undefined : true}
      tabIndex={interactive ? undefined : -1}
      onClick={onClick}
      className={cn(
        "no-drag min-w-0",
        // `shrink` beats quill's own `shrink-0`. Only the leaf takes it: a
        // segment that cannot shrink keeps its full width in a row that has
        // run out, and paints its label over the marks after it. The fixed
        // segments stay whole, so a long session name is what gives.
        shrink && "shrink",
        // Live segments (a link, or a click-to-rename leaf) behave like
        // any other button: pointer cursor and hover fill. Inert ones read as
        // plain text — full opacity, ordinary cursor, and no hover (quill's
        // hover rules already skip aria-disabled) — and leave the tab order.
        interactive || contextMenu
          ? "cursor-pointer!"
          : "pointer-events-none cursor-default! opacity-100!",
        className,
      )}
    >
      {icon && (
        <span className="flex shrink-0 text-muted-foreground/80">{icon}</span>
      )}
      {/* No `title`: the native tooltip duplicated the styled one, and on the
          fixed segments there was nothing worth revealing. */}
      <Text
        className={cn(
          "min-w-0 truncate whitespace-nowrap text-[13px]",
          strong && "font-medium",
          muted && "text-muted-foreground",
        )}
      >
        {label}
      </Text>
    </Button>
  );
}

function ChannelSegmentContextMenu({
  channelId,
  children,
}: {
  channelId: string;
  children: ReactNode;
}) {
  const { channels } = useChannels();
  const { star, unstar } = useChannelStarMutations();
  const channel = channels.find((candidate) => candidate.id === channelId);
  const canStar = channel != null && channel.channelType !== "personal";
  const isStarred = channel?.starred ?? false;

  const toggleStar = async () => {
    try {
      await (isStarred ? unstar(channelId) : star(channelId));
      track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
        action_type: isStarred ? "unstar" : "star",
        surface: "title_bar",
        channel_id: channelId,
      });
    } catch (error) {
      toast.error(
        isStarred ? "Couldn't unstar channel" : "Couldn't star channel",
        {
          description: error instanceof Error ? error.message : String(error),
        },
      );
    }
  };

  return (
    <ContextMenu>
      <ContextMenuTrigger render={<span className="flex min-w-0" />}>
        {children}
      </ContextMenuTrigger>
      <ContextMenuContent className="no-drag">
        {canStar && (
          <>
            <ContextMenuItem onClick={() => void toggleStar()}>
              <StarIcon size={14} weight={isStarred ? "fill" : "regular"} />
              {isStarred ? "Unstar channel" : "Star channel"}
            </ContextMenuItem>
            <ContextMenuSeparator />
          </>
        )}
        <ContextMenuItem
          onClick={() => void copyChannelLink(channelId, "title_bar")}
        >
          <LinkIcon size={14} />
          Copy link to channel
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}

function BreadcrumbSeparator() {
  return (
    <Text className="shrink-0 text-[13px] text-muted-foreground/20">/</Text>
  );
}
