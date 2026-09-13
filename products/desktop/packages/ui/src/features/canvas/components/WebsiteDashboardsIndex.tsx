import { DotsThreeIcon, LinkIcon, TrashIcon } from "@phosphor-icons/react";
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
import { NewCanvasMenu } from "@posthog/ui/features/canvas/components/NewCanvasMenu";
import { deleteCanvasWithUndo } from "@posthog/ui/features/canvas/deleteCanvasWithUndo";
import { useCanvasTemplates } from "@posthog/ui/features/canvas/hooks/useCanvasTemplates";
import {
  useDashboardMutations,
  useDashboards,
} from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useIsCanvasPendingDelete } from "@posthog/ui/features/canvas/stores/pendingCanvasDeleteStore";
import { copyCanvasLink } from "@posthog/ui/features/canvas/utils/copyCanvasLink";
import { track } from "@posthog/ui/shell/analytics";
import { Box, Flex, Grid } from "@radix-ui/themes";
import { Link } from "@tanstack/react-router";
import { memo, useState } from "react";

// A channel's dashboards index: a grid of cards, each showing a scaled-down
// live preview. Clicking a card opens the full dashboard.
export function WebsiteDashboardsIndex({ channelId }: { channelId: string }) {
  const { dashboards, isLoading } = useDashboards(channelId);

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

  return (
    <div className="scroll-mask-4 h-full overflow-auto bg-gray-1">
      <Box className="p-5">
        <Grid columns={{ initial: "1", sm: "2", md: "3" }} gap="4">
          {dashboards.map((d) => (
            <DashboardCard
              key={d.id}
              channelId={channelId}
              summary={d}
              templateLabel={templateLabels.get(d.templateId) ?? d.templateId}
            />
          ))}
        </Grid>
      </Box>
    </div>
  );
}

const DashboardCard = memo(function DashboardCard({
  channelId,
  summary,
  templateLabel,
}: {
  channelId: string;
  summary: DashboardRecord;
  templateLabel: string;
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
          <PreviewFrame />
          <CardContent className="flex flex-col gap-0.5 p-3">
            <Flex align="center" justify="between" gap="2">
              <Text size="sm" weight="medium" className="truncate">
                {summary.name}
              </Text>
              <Badge>{templateLabel}</Badge>
            </Flex>
            <Text size="xxs" variant="muted">
              Updated {formatRelativeTimeShort(summary.updatedAt)}
            </Text>

            <Text size="xxs" variant="muted">
              Created by{" "}
              {summary.createdBy ? `${summary.createdBy}` : "Unknown"}
            </Text>
          </CardContent>
        </Card>
      </Link>
      {/* Sibling of the Link (not nested) so opening the menu or deleting never
          navigates into the dashboard. */}
      <DashboardCardMenu
        id={summary.id}
        name={summary.name}
        channelId={channelId}
      />
    </Box>
  );
});

// The card's preview frame. Canvas records no longer carry source code — the
// rendered output is the published build's artifact, wired up separately — so
// the grid shows a stable placeholder frame instead of a live per-card render.
function PreviewFrame() {
  return (
    <Box className="relative h-44 overflow-hidden border-border border-b bg-muted">
      <PreviewPlaceholder label="Canvas preview" />
    </Box>
  );
}

function DashboardCardMenu({
  id,
  name,
  channelId,
}: {
  id: string;
  name: string;
  channelId: string;
}) {
  const [open, setOpen] = useState(false);
  const { invalidateDashboards } = useDashboardMutations();

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
          <DropdownMenuItem variant="destructive" onClick={onDelete}>
            <TrashIcon size={14} />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </Box>
  );
}

function PreviewPlaceholder({ label }: { label: string }) {
  return (
    <Flex
      align="center"
      justify="center"
      className="absolute inset-0 text-center"
    >
      <Text size="xs" variant="muted">
        {label}
      </Text>
    </Flex>
  );
}
