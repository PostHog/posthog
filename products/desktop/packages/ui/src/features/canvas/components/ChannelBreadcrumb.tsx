import { LinkIcon, StarIcon } from "@phosphor-icons/react";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
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
import {
  BreadcrumbSegment,
  BreadcrumbSeparator,
} from "@posthog/ui/primitives/Breadcrumb";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { Flex } from "@radix-ui/themes";
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
