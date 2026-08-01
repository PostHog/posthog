import { CaretRightIcon, FilesIcon, TrashIcon } from "@phosphor-icons/react";
import type { ChannelTaskRecord } from "@posthog/core/canvas/channelTaskSchemas";
import type { DashboardSummary } from "@posthog/core/canvas/dashboardSchemas";
import {
  Badge,
  Card,
  CardContent,
  cn,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Text,
} from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { ArtifactsViewToggle } from "@posthog/ui/features/canvas/components/ArtifactsViewToggle";
import { ChannelHeader } from "@posthog/ui/features/canvas/components/ChannelHeader";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import { FreeformPreview } from "@posthog/ui/features/canvas/components/FreeformPreview";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useChannelTasks } from "@posthog/ui/features/canvas/hooks/useChannelTasks";
import { useDashboards } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useArtifactsViewStore } from "@posthog/ui/features/canvas/stores/artifactsViewStore";
import { useIsCanvasPendingDelete } from "@posthog/ui/features/canvas/stores/pendingCanvasDeleteStore";
import { masonryPreviewHeight } from "@posthog/ui/features/canvas/utils/masonryPreviewHeight";
import { usePrArtifact } from "@posthog/ui/features/git-interaction/usePrArtifact";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import {
  PageHeader,
  PageHeaderActions,
  PageHeaderChip,
  PageHeaderDescription,
  PageHeaderHeading,
  PageHeaderTitle,
  PageHeaderTitleRow,
} from "@posthog/ui/primitives/PageHeader";
import { track } from "@posthog/ui/shell/analytics";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useNavigate } from "@tanstack/react-router";
import { type ReactNode, useCallback, useEffect, useMemo } from "react";

// Uniform media height for the grid: cards line up row to row, and a PR tile
// (which has nothing to preview) fills the same band as a canvas thumbnail.
const GRID_PREVIEW_HEIGHT = 176;

// Artifacts are the durable outputs of a channel's work. Canvases for now; PRs
// are surfaced from each filed task's latest run output. More kinds (reports,
// files, …) slot into this union later.
type ArtifactItem =
  | {
      kind: "canvas";
      key: string;
      title: string;
      ts: number;
      templateId: string;
      dashboardId: string;
      /** Live React source, along for the ride so cards preview without a get(). */
      code?: string;
    }
  | {
      kind: "pr";
      key: string;
      title: string;
      ts: number;
      prUrl: string;
    };

// A channel's artifacts: canvases and the pull requests produced by its tasks,
// most recent first. Sibling of the History tab, but scoped to outputs rather
// than the full activity stream. The view toggle switches between a dense row
// list and card layouts that preview each canvas live.
export function WebsiteChannelArtifacts({ channelId }: { channelId: string }) {
  const spacesLayout = useChannelsLayout();
  const navigate = useNavigate();
  const view = useArtifactsViewStore((s) => s.view);

  useEffect(() => {
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "view_artifacts",
      surface: "channel_artifacts",
      channel_id: channelId,
    });
  }, [channelId]);

  useSetHeaderContent(
    useMemo(
      () => <ChannelHeader channelId={channelId} page="artifacts" />,
      [channelId],
    ),
  );

  const { dashboards } = useDashboards(channelId);
  const { tasks: filedTasks } = useChannelTasks(channelId);
  const { data: tasks } = useTasks();
  const archivedTaskIds = useArchivedTaskIds();

  const items = useMemo<ArtifactItem[]>(() => {
    const canvasItems: ArtifactItem[] = dashboards.map(
      (d: DashboardSummary) => ({
        kind: "canvas",
        key: `canvas:${d.id}`,
        title: d.name,
        ts: d.updatedAt,
        templateId: d.templateId,
        dashboardId: d.id,
        code: d.code,
      }),
    );

    const taskById = new Map(tasks?.map((t) => [t.id, t]) ?? []);
    type PrArtifact = Extract<ArtifactItem, { kind: "pr" }>;
    const prItems: PrArtifact[] = filedTasks.flatMap((f: ChannelTaskRecord) => {
      const task = taskById.get(f.taskId);
      const prUrl = task?.latest_run?.output?.pr_url;
      if (archivedTaskIds.has(f.taskId) || !task) return [];
      if (typeof prUrl !== "string" || !prUrl) return [];
      return [
        {
          kind: "pr" as const,
          key: `pr:${f.id}`,
          title: task.title || "Pull request",
          ts: Date.parse(task.updated_at) || 0,
          prUrl,
        },
      ];
    });

    // Most recent first.
    return [...canvasItems, ...prItems].sort((a, b) => b.ts - a.ts);
  }, [dashboards, filedTasks, tasks, archivedTaskIds]);

  const openCanvas = useCallback(
    (dashboardId: string) => {
      track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
        action_type: "open_artifact",
        surface: "channel_artifacts",
        channel_id: channelId,
      });
      void navigate({
        to: "/website/$channelId/dashboards/$dashboardId",
        params: { channelId, dashboardId },
      });
    },
    [channelId, navigate],
  );

  const openPr = useCallback(
    (prUrl: string) => {
      track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
        action_type: "open_artifact",
        surface: "channel_artifacts",
        channel_id: channelId,
      });
      openExternalUrl(prUrl);
    },
    [channelId],
  );

  return (
    <div className="flex h-full min-h-0 flex-col bg-gray-1">
      {/* Full-bleed header over a container-width body — the Inbox shape. Ships
          behind the spaces layout like every other space page header; off,
          the view switcher rides above the list instead. */}
      {spacesLayout ? (
        <PageHeader>
          <PageHeaderHeading>
            <PageHeaderTitleRow>
              <PageHeaderTitle>Artifacts</PageHeaderTitle>
              {items.length > 0 && (
                <PageHeaderChip icon={<FilesIcon size={12} weight="fill" />}>
                  {items.length} item{items.length === 1 ? "" : "s"}
                </PageHeaderChip>
              )}
              <PageHeaderActions>
                <ArtifactsViewToggle channelId={channelId} />
              </PageHeaderActions>
            </PageHeaderTitleRow>
            <PageHeaderDescription>
              Canvases and pull requests from this{" "}
              {spacesLayout ? "space's" : "channel's"} tasks.
            </PageHeaderDescription>
          </PageHeaderHeading>
        </PageHeader>
      ) : null}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {/* Full width, flush with the page header above it — every layout
            here (rows and cards alike) is a scannable list, not prose, so a
            measure cap just strands whitespace on wide windows. */}
        <div className="w-full px-6 py-6">
          {!spacesLayout && (
            <div className="mb-3 flex items-center justify-between gap-3">
              <Text size="sm" variant="muted">
                {items.length === 0
                  ? "Artifacts"
                  : `${items.length} artifact${items.length === 1 ? "" : "s"}`}
              </Text>
              <ArtifactsViewToggle channelId={channelId} />
            </div>
          )}
          {items.length === 0 ? (
            <Empty className="mx-auto max-w-md py-20">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <FilesIcon size={24} />
                </EmptyMedia>
                <EmptyTitle>No artifacts yet</EmptyTitle>
                <EmptyDescription>
                  Canvases and pull requests from this{" "}
                  {spacesLayout ? "space's" : "channel's"} tasks show up here.
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : view === "list" ? (
            <div className="flex flex-col gap-0.5">
              {items.map((item) => (
                <ArtifactListItem
                  key={item.key}
                  item={item}
                  onOpenCanvas={openCanvas}
                  onOpenPr={openPr}
                />
              ))}
            </div>
          ) : view === "grid" ? (
            // items-stretch + a full-height card: a PR tile (no preview to
            // show) matches the canvas cards in its row instead of ending
            // short.
            <div className="grid grid-cols-1 items-stretch gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
              {items.map((item) => (
                <ArtifactCard
                  key={item.key}
                  item={item}
                  previewHeight={GRID_PREVIEW_HEIGHT}
                  fillHeight
                  onOpenCanvas={openCanvas}
                  onOpenPr={openPr}
                />
              ))}
            </div>
          ) : (
            // CSS columns rather than a JS masonry: cards are self-contained and
            // never reflow into each other, so break-inside-avoid is enough. The
            // trade-off is column-major order — newest runs down column one, not
            // across the row — which is fine for a browse-y wall of previews.
            <div className="columns-1 gap-4 sm:columns-2 lg:columns-3 2xl:columns-4">
              {items.map((item) => (
                <div key={item.key} className="mb-4 break-inside-avoid">
                  <ArtifactCard
                    item={item}
                    previewHeight={masonryPreviewHeight(item.key)}
                    onOpenCanvas={openCanvas}
                    onOpenPr={openPr}
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ArtifactListItem({
  item,
  onOpenCanvas,
  onOpenPr,
}: {
  item: ArtifactItem;
  onOpenCanvas: (dashboardId: string) => void;
  onOpenPr: (safeUrl: string) => void;
}) {
  return item.kind === "canvas" ? (
    <CanvasArtifactRow
      dashboardId={item.dashboardId}
      templateId={item.templateId}
      title={item.title}
      ts={item.ts}
      onClick={onOpenCanvas}
    />
  ) : (
    <PrArtifactRow
      title={item.title}
      prUrl={item.prUrl}
      ts={item.ts}
      onClick={onOpenPr}
    />
  );
}

function ArtifactCard({
  item,
  previewHeight,
  fillHeight,
  onOpenCanvas,
  onOpenPr,
}: {
  item: ArtifactItem;
  previewHeight: number;
  /** Grid only: stretch to the tallest card in the row. */
  fillHeight?: boolean;
  onOpenCanvas: (dashboardId: string) => void;
  onOpenPr: (safeUrl: string) => void;
}) {
  return item.kind === "canvas" ? (
    <CanvasArtifactCard
      dashboardId={item.dashboardId}
      templateId={item.templateId}
      title={item.title}
      ts={item.ts}
      code={item.code}
      previewHeight={previewHeight}
      fillHeight={fillHeight}
      onClick={onOpenCanvas}
    />
  ) : (
    <PrArtifactCard
      title={item.title}
      prUrl={item.prUrl}
      ts={item.ts}
      mediaHeight={fillHeight ? previewHeight : undefined}
      fillHeight={fillHeight}
      onClick={onOpenPr}
    />
  );
}

// A canvas artifact row. While the canvas is inside its delete-undo window the
// row stays put — its template icon becomes a pulsing trash can and the row
// stops opening — so undoing puts it back exactly where it was.
function CanvasArtifactRow({
  dashboardId,
  templateId,
  title,
  ts,
  onClick,
}: {
  dashboardId: string;
  templateId: string;
  title: string;
  ts: number;
  onClick: (dashboardId: string) => void;
}) {
  const deleting = useIsCanvasPendingDelete(dashboardId);

  return (
    <ArtifactRow
      accent={deleting ? "red" : "violet"}
      icon={
        deleting ? (
          <TrashIcon size={15} className="animate-pulse text-red-9" />
        ) : (
          iconForTemplate(templateId, { size: 15, className: "text-violet-9" })
        )
      }
      title={title}
      subtitle={
        deleting ? "Deleting…" : `Canvas · ${formatRelativeTimeShort(ts)}`
      }
      onClick={deleting ? undefined : () => onClick(dashboardId)}
    />
  );
}

// A PR artifact row. The PR's lifecycle state (open / draft / merged / closed)
// comes from usePrArtifact, which also gates the URL — PR links come from run
// output, so a row must not fetch from whatever host that names.
function PrArtifactRow({
  title,
  prUrl,
  ts,
  onClick,
}: {
  title: string;
  prUrl: string;
  ts: number;
  onClick: (safeUrl: string) => void;
}) {
  const {
    safeUrl,
    title: prTitle,
    stateLabel,
    Icon,
    iconColor,
    accentColor,
  } = usePrArtifact(prUrl);

  const subtitle = [prTitle, stateLabel, formatRelativeTimeShort(ts)]
    .filter(Boolean)
    .join(" · ");

  return (
    <ArtifactRow
      accent={accentColor}
      icon={<Icon size={15} weight="bold" style={{ color: iconColor }} />}
      title={title}
      subtitle={subtitle}
      onClick={safeUrl ? () => onClick(safeUrl) : undefined}
    />
  );
}

function ArtifactRow({
  icon,
  accent,
  title,
  subtitle,
  onClick,
}: {
  icon: ReactNode;
  accent: string;
  title: string;
  subtitle: string;
  /** Absent for a row with nowhere safe to go — a non-github PR link. */
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!onClick}
      className="group flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors enabled:hover:bg-fill-hover"
    >
      <span
        className="flex size-7 shrink-0 items-center justify-center rounded-md"
        style={{ backgroundColor: `var(--${accent}-3)` }}
      >
        {icon}
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate font-medium text-[13px] text-gray-12 leading-tight">
          {title}
        </span>
        <span className="truncate text-[11px] text-muted-foreground leading-tight">
          {subtitle}
        </span>
      </span>
      <CaretRightIcon
        size={14}
        className="shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
      />
    </button>
  );
}

// The card form of a canvas artifact: a live preview of the canvas above its
// title. Same delete-undo behaviour as the row — the card stays in place,
// dimmed, until the undo window closes.
function CanvasArtifactCard({
  dashboardId,
  templateId,
  title,
  ts,
  code,
  previewHeight,
  fillHeight,
  onClick,
}: {
  dashboardId: string;
  templateId: string;
  title: string;
  ts: number;
  code?: string;
  previewHeight: number;
  fillHeight?: boolean;
  onClick: (dashboardId: string) => void;
}) {
  const deleting = useIsCanvasPendingDelete(dashboardId);

  return (
    <ArtifactCardShell
      media={
        <>
          <FreeformPreview
            code={code}
            height={previewHeight}
            className="border-border border-b"
          />
          {deleting && (
            <div className="absolute inset-0 flex items-center justify-center gap-2 bg-gray-1/80">
              <TrashIcon size={18} className="animate-pulse text-red-9" />
              <Text size="xs" variant="muted">
                Deleting…
              </Text>
            </div>
          )}
        </>
      }
      icon={iconForTemplate(templateId, {
        size: 14,
        className: "text-violet-9",
      })}
      title={title}
      badge="Canvas"
      subtitle={
        deleting ? "Deleting…" : `Updated ${formatRelativeTimeShort(ts)}`
      }
      dimmed={deleting}
      fillHeight={fillHeight}
      onClick={deleting ? undefined : () => onClick(dashboardId)}
    />
  );
}

// The card form of a PR artifact. A PR has nothing to preview, so its media
// slot is a short tinted band carrying the lifecycle icon — which also keeps PR
// cards visibly shorter than canvas cards in the masonry layout.
function PrArtifactCard({
  title,
  prUrl,
  ts,
  mediaHeight,
  fillHeight,
  onClick,
}: {
  title: string;
  prUrl: string;
  ts: number;
  /** Grid only: match the canvas thumbnails' band instead of a short strip. */
  mediaHeight?: number;
  fillHeight?: boolean;
  onClick: (safeUrl: string) => void;
}) {
  const {
    safeUrl,
    title: prTitle,
    stateLabel,
    Icon,
    iconColor,
    accentColor,
  } = usePrArtifact(prUrl);

  const subtitle = [prTitle, formatRelativeTimeShort(ts)]
    .filter(Boolean)
    .join(" · ");

  return (
    <ArtifactCardShell
      media={
        <div
          className="flex items-center justify-center border-border border-b"
          style={{
            backgroundColor: `var(--${accentColor}-3)`,
            height: mediaHeight ?? 80,
          }}
        >
          <Icon size={28} weight="bold" style={{ color: iconColor }} />
        </div>
      }
      icon={<Icon size={14} weight="bold" style={{ color: iconColor }} />}
      title={title}
      badge={stateLabel || "Pull request"}
      subtitle={subtitle}
      fillHeight={fillHeight}
      onClick={safeUrl ? () => onClick(safeUrl) : undefined}
    />
  );
}

function ArtifactCardShell({
  media,
  icon,
  title,
  badge,
  subtitle,
  dimmed,
  fillHeight,
  onClick,
}: {
  media: ReactNode;
  icon: ReactNode;
  title: string;
  badge: string;
  subtitle: string;
  dimmed?: boolean;
  /** Grid only: fill the row so neighbouring cards end at the same line. */
  fillHeight?: boolean;
  /** Absent for a card with nowhere safe to go — a non-github PR link. */
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!onClick}
      className={cn(
        // A card with nowhere to go (or mid-delete) takes no pointer events, so
        // the hover treatment below can key off plain group-hover.
        "group w-full text-left disabled:pointer-events-none",
        fillHeight && "h-full",
        dimmed && "pointer-events-none opacity-60",
      )}
    >
      <Card
        className={cn(
          "gap-0 overflow-hidden p-0 transition-colors group-hover:border-accent",
          fillHeight && "flex h-full flex-col",
        )}
      >
        <div className="relative shrink-0">{media}</div>
        <CardContent className="flex flex-1 flex-col gap-0.5 p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="flex min-w-0 items-center gap-1.5">
              <span className="shrink-0">{icon}</span>
              <Text size="sm" weight="medium" className="truncate">
                {title}
              </Text>
            </div>
            <Badge>{badge}</Badge>
          </div>
          <Text size="xxs" variant="muted" className="truncate">
            {subtitle}
          </Text>
        </CardContent>
      </Card>
    </button>
  );
}
