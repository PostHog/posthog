import {
  Button,
  cn,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { HeaderTitleEditor } from "@posthog/ui/features/task-detail/HeaderTitleEditor";
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
}: ChannelBreadcrumbProps) {
  const spacesLayout = useChannelsLayout();
  // Only a leaf is renamable, so the scope key falls back to its label.
  const currentEditScope = editScopeKey ?? leafLabel ?? "";
  const [editingScope, setEditingScope] = useState<string | null>(null);
  const editing = editingScope === currentEditScope;
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const atChannelHome = channelId
    ? pathname === `/website/${channelId}`
    : false;

  return (
    <Flex align="center" justify="between" gap="2" className="w-full min-w-0">
      {/* flex-1 so the inline editor can stretch across the row; the trailing
          slot still sits at the far end. */}
      <Flex align="center" gap="0.5" className="min-w-0 flex-1">
        <BreadcrumbSegment
          icon={channelGlyph(channelName, {
            size: 12,
            space: spacesLayout,
            className: "shrink-0 text-muted-foreground/80",
          })}
          label={channelName}
          strong
          // Nowhere to go from the space's own index, and no channelId means no
          // route at all — either way the segment stops responding.
          onClick={
            channelId && !atChannelHome
              ? () =>
                  void navigate({
                    to: "/website/$channelId",
                    params: { channelId },
                  })
              : undefined
          }
        />
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
              // Matches the segment it replaces — same height, padding and type
              // scale as a `size="sm"` button — so opening the editor doesn't
              // jump the row. It takes the rest of the row, since a long name is
              // exactly what you're most likely to be editing.
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
              // Only a renamable leaf gets a tooltip: it carries a user-authored
              // name that can be long enough to truncate. Fixed section labels
              // never overflow, so a tooltip there is just noise.
              <Tooltip>
                <TooltipTrigger render={<span className="flex min-w-0" />}>
                  {/* A renamable leaf is a live control — a click opens the
                      editor — so it reads as one: full-strength text, pointer
                      cursor, hover fill. */}
                  <BreadcrumbSegment
                    icon={leafIcon}
                    label={leafLabel}
                    onClick={() => setEditingScope(currentEditScope)}
                  />
                </TooltipTrigger>
                <TooltipContent>{leafLabel}</TooltipContent>
              </Tooltip>
            ) : (
              <BreadcrumbSegment icon={leafIcon} label={leafLabel} muted />
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
  onClick,
  ...rest
}: {
  icon?: ReactNode;
  label: string;
  /** The root segment carries the space name, which reads heavier. */
  strong?: boolean;
  /** The leaf is the current page, so it sits back from the linked segments. */
  muted?: boolean;
  /** Navigates, or (on a renamable leaf) opens the inline editor. */
  onClick?: () => void;
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
        // Live segments (a link, or a click-to-rename leaf) behave like
        // any other button: pointer cursor and hover fill. Inert ones read as
        // plain text — full opacity, ordinary cursor, and no hover (quill's
        // hover rules already skip aria-disabled) — and leave the tab order.
        interactive
          ? "cursor-pointer!"
          : "pointer-events-none cursor-default! opacity-100!",
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

function BreadcrumbSeparator() {
  return (
    <Text className="shrink-0 text-[13px] text-muted-foreground/20">/</Text>
  );
}
