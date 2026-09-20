import {
  DotsThreeIcon,
  LinkIcon,
  PushPinIcon,
  PushPinSlashIcon,
  TrashIcon,
} from "@phosphor-icons/react";
import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import {
  Badge,
  Button,
  Card,
  CardContent,
  cn,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Text,
} from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { AvatarPerson } from "@posthog/ui/features/auth/UserAvatar";
import { CanvasPreviewFrame } from "@posthog/ui/features/canvas/components/CanvasPreviewFrame";
import { ActivityPresenceAvatar } from "@posthog/ui/features/canvas/components/ChannelItemPresence";
import { NewCanvasMenu } from "@posthog/ui/features/canvas/components/NewCanvasMenu";
import { deleteCanvasWithUndo } from "@posthog/ui/features/canvas/deleteCanvasWithUndo";
import { useCanvasTemplates } from "@posthog/ui/features/canvas/hooks/useCanvasTemplates";
import {
  useDashboardMutations,
  useDashboards,
} from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useIsCanvasPendingDelete } from "@posthog/ui/features/canvas/stores/pendingCanvasDeleteStore";
import { copyCanvasLink } from "@posthog/ui/features/canvas/utils/copyCanvasLink";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { Box, Flex } from "@radix-ui/themes";
import { Link } from "@tanstack/react-router";
import { memo, useState } from "react";

// A channel's dashboards index: a grid of cards, each showing a scaled-down
// live preview. Clicking a card opens the full dashboard.
export function WebsiteDashboardsIndex({
  channelId,
  variant = "page",
}: {
  channelId: string;
  variant?: "page" | "work";
}) {
  const { dashboards, isLoading } = useDashboards(channelId);
  const isWork = variant === "work";

  // templateId -> display name, for the per-card badge ("Freeform (React)", …).
  // Falls back to the raw id for any template not in the registry.
  const templates = useCanvasTemplates();
  const templateLabels = new Map(templates.map((t) => [t.id, t.name]));

  if (isLoading) return null;

  if (dashboards.length === 0) {
    return (
      <Flex
        direction="column"
        align="center"
        justify="center"
        height="100%"
        gap="3"
        className="px-6 text-center"
      >
        <Flex direction="column" gap="1">
          <Text size="lg" weight="semibold">
            No canvases yet
          </Text>
          <Text size="sm" variant="muted">
            Create one and build it with the agent, then save it.
          </Text>
        </Flex>
        <NewCanvasMenu channelId={channelId} variant="primary" />
      </Flex>
    );
  }

  const card = (d: DashboardRecord) => (
    <DashboardCard
      key={d.id}
      channelId={channelId}
      summary={d}
      templateLabel={templateLabels.get(d.templateId) ?? d.templateId}
      canPin={isWork}
      compactMeta={isWork}
    />
  );

  if (!isWork) {
    return (
      <div className="scroll-mask-4 h-full overflow-auto bg-gray-1">
        <div className="p-5">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3">
            {dashboards.map(card)}
          </div>
        </div>
      </div>
    );
  }

  const pinned = dashboards
    .filter((d) => d.pinnedAt != null)
    .sort((a, b) => (b.pinnedAt ?? 0) - (a.pinnedAt ?? 0));
  const rest = dashboards.filter((d) => d.pinnedAt == null);
  const countLabel =
    dashboards.length === 1 ? "1 canvas" : `${dashboards.length} canvases`;

  return (
    <div className="scroll-mask-4 h-full overflow-auto bg-gray-1">
      <div className="px-6 py-5">
        <div className="mb-3 flex items-center justify-between">
          <Text size="xs" variant="muted">
            {countLabel}
          </Text>
          <NewCanvasMenu channelId={channelId} />
        </div>
        {pinned.length > 0 && (
          <>
            <Text
              size="xxs"
              variant="muted"
              className="mb-2 block font-medium uppercase tracking-wider"
            >
              Pinned
            </Text>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3">
              {pinned.map(card)}
            </div>
            {rest.length > 0 && (
              <Text
                size="xxs"
                variant="muted"
                className="mt-5 mb-2 block font-medium uppercase tracking-wider"
              >
                All
              </Text>
            )}
          </>
        )}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3">
          {rest.map(card)}
        </div>
      </div>
    </div>
  );
}

function canvasAuthor(summary: DashboardRecord): AvatarPerson | null {
  if (summary.createdByUser) return summary.createdByUser;
  if (!summary.createdBy && !summary.createdByUuid) return null;
  const [first, ...rest] = (summary.createdBy ?? "")
    .split(/\s+/)
    .filter(Boolean);
  return {
    uuid: summary.createdByUuid,
    first_name: first ?? null,
    last_name: rest.join(" ") || null,
  };
}

const DashboardCard = memo(function DashboardCard({
  channelId,
  summary,
  templateLabel,
  canPin = false,
  compactMeta = false,
}: {
  channelId: string;
  summary: DashboardRecord;
  templateLabel: string;
  canPin?: boolean;
  compactMeta?: boolean;
}) {
  // Inside its delete-undo window the card stays in the grid (Undo puts it
  // straight back) but is dimmed and inert.
  const pendingDelete = useIsCanvasPendingDelete(summary.id);
  return (
    <Box
      className={cn(
        "group relative",
        pendingDelete && "pointer-events-none opacity-50",
      )}
    >
      <Link
        to="/spaces/$channelId/dashboards/$dashboardId"
        params={{ channelId, dashboardId: summary.id }}
        className="no-underline"
        onClick={() =>
          track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
            action_type: "open",
            surface: "dashboards_grid",
            channel_id: channelId,
            dashboard_id: summary.id,
            template_id: summary.templateId,
          })
        }
      >
        <Card className="gap-0 overflow-hidden p-0">
          <PreviewFrame dashboardId={summary.id} />
          <CardContent className="flex flex-col gap-1 p-3">
            <div className="flex items-center justify-between gap-2">
              <Text size="sm" weight="medium" className="min-w-0 truncate">
                {summary.name}
              </Text>
              {/* Whose canvas, and whether they are in it now: the same mark
                  the session rows wear, from the same activity clock. */}
              <ActivityPresenceAvatar
                user={canvasAuthor(summary)}
                label="on this canvas"
                activityAt={summary.updatedAt}
              />
              {!compactMeta && <Badge>{templateLabel}</Badge>}
            </div>
            {compactMeta ? (
              <Text size="xxs" variant="muted" className="truncate">
                {templateLabel} · updated{" "}
                {formatRelativeTimeShort(summary.updatedAt)}
                {summary.createdBy ? ` · ${summary.createdBy}` : ""}
              </Text>
            ) : (
              <>
                <Text size="xxs" variant="muted">
                  Updated {formatRelativeTimeShort(summary.updatedAt)}
                </Text>
                <Text size="xxs" variant="muted">
                  Created by{" "}
                  {summary.createdBy ? `${summary.createdBy}` : "Unknown"}
                </Text>
              </>
            )}
          </CardContent>
        </Card>
      </Link>
      {/* Sibling of the Link (not nested) so opening the menu or deleting never
          navigates into the dashboard. */}
      <DashboardCardMenu
        id={summary.id}
        name={summary.name}
        channelId={channelId}
        pinned={canPin ? summary.pinnedAt != null : undefined}
      />
    </Box>
  );
});

function PreviewFrame({ dashboardId }: { dashboardId: string }) {
  return (
    <div className="relative h-44 overflow-hidden border-border border-b bg-muted">
      <CanvasPreviewFrame dashboardId={dashboardId} className="h-full w-full" />
    </div>
  );
}

function DashboardCardMenu({
  id,
  name,
  channelId,
  pinned,
}: {
  id: string;
  name: string;
  channelId: string;
  pinned?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const { invalidateDashboards, setPinned } = useDashboardMutations();

  const onTogglePin = () => {
    setPinned(id, !pinned).catch(() => {
      toast.error("Couldn't update pin");
    });
  };

  const onDelete = () => {
    deleteCanvasWithUndo({
      dashboardId: id,
      channelId,
      name,
      surface: "dashboards_grid",
      invalidate: invalidateDashboards,
    });
  };

  return (
    <Box
      className={cn(
        "absolute top-2 right-2 transition-opacity",
        open ? "opacity-100" : "opacity-0 group-hover:opacity-100",
      )}
    >
      <DropdownMenu open={open} onOpenChange={setOpen}>
        <DropdownMenuTrigger
          render={
            <Button
              variant="outline"
              size="sm"
              aria-label={`Options for ${name}`}
            >
              <DotsThreeIcon size={16} weight="bold" />
            </Button>
          }
        />
        <DropdownMenuContent align="end" side="bottom" sideOffset={4}>
          <DropdownMenuItem
            onClick={() =>
              void copyCanvasLink(channelId, id, "dashboards_grid")
            }
          >
            <LinkIcon size={14} />
            Copy link
          </DropdownMenuItem>
          {pinned !== undefined && (
            <DropdownMenuItem onClick={onTogglePin}>
              {pinned ? (
                <PushPinSlashIcon size={14} />
              ) : (
                <PushPinIcon size={14} />
              )}
              {pinned ? "Unpin" : "Pin"}
            </DropdownMenuItem>
          )}
          <DropdownMenuItem variant="destructive" onClick={onDelete}>
            <TrashIcon size={14} />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </Box>
  );
}
