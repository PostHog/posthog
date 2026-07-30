import { DotsThreeIcon, LinkIcon, TrashIcon } from "@phosphor-icons/react";
import type { DashboardSummary } from "@posthog/core/canvas/dashboardSchemas";
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
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
import { FreeformPreview } from "@posthog/ui/features/canvas/components/FreeformPreview";
import { NewCanvasMenu } from "@posthog/ui/features/canvas/components/NewCanvasMenu";
import { deleteCanvasWithUndo } from "@posthog/ui/features/canvas/deleteCanvasWithUndo";
import { useCanvasTemplates } from "@posthog/ui/features/canvas/hooks/useCanvasTemplates";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
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
  summary: DashboardSummary;
  templateLabel: string;
}) {
  // While the canvas is inside its delete-undo window the card stays in the
  // grid — dimmed, with a pulsing trash can over its preview — so undoing puts
  // it back exactly where it was rather than re-inserting a row.
  const deleting = useIsCanvasPendingDelete(summary.id);

  // The React source rides along in the list response, so the grid renders
  // previews without a per-card fetch (no N+1 of get()).
  return (
    <Box
      className={cn(
        "group relative",
        deleting && "pointer-events-none opacity-60",
      )}
    >
      <Link
        to="/website/$channelId/dashboards/$dashboardId"
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
          <Box className="relative">
            <FreeformPreview
              code={summary.code}
              className="border-border border-b"
            />
            {deleting && (
              <Flex
                align="center"
                justify="center"
                gap="2"
                className="absolute inset-0 bg-gray-1/80"
              >
                <TrashIcon size={18} className="animate-pulse text-red-9" />
                <Text size="xs" variant="muted">
                  Deleting…
                </Text>
              </Flex>
            )}
          </Box>
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
  const spacesLayout = useChannelsLayout();
  const containerNoun = spacesLayout ? "space" : "channel";
  // "Delete…" opens a confirmation rather than deleting inline — the canvas and
  // its version history go away for everyone in the space.
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const { invalidateDashboards } = useDashboardMutations();

  // The card disappears immediately, but the delete isn't sent until the undo
  // toast's timer runs out — Undo simply cancels it.
  const confirmDelete = () => {
    setConfirmDeleteOpen(false);
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
          <DropdownMenuItem
            variant="destructive"
            onClick={() => setConfirmDeleteOpen(true)}
          >
            <TrashIcon size={14} />
            Delete…
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      {/* Destructive confirm for "Delete…" — the canvas goes for everyone. */}
      <AlertDialog open={confirmDeleteOpen} onOpenChange={setConfirmDeleteOpen}>
        <AlertDialogContent className="max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>Delete canvas</AlertDialogTitle>
            <AlertDialogDescription>
              Delete <span className="font-medium">{name}</span>? Its code and
              version history go for everyone in the {containerNoun}. You get a
              few seconds to undo, then it's permanent.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogClose
              render={
                <Button variant="outline" size="sm">
                  Cancel
                </Button>
              }
            />
            <Button variant="destructive" size="sm" onClick={confirmDelete}>
              Delete
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Box>
  );
}
