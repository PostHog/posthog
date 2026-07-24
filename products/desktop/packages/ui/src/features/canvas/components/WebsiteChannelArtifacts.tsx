import { CaretRightIcon } from "@phosphor-icons/react";
import type { ChannelTaskRecord } from "@posthog/core/canvas/channelTaskSchemas";
import type { DashboardSummary } from "@posthog/core/canvas/dashboardSchemas";
import {
  getPrVisualConfig,
  parsePrNumber,
} from "@posthog/core/git-interaction/prStatus";
import { formatRelativeTimeShort } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { ChannelHeader } from "@posthog/ui/features/canvas/components/ChannelHeader";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import { useChannelTasks } from "@posthog/ui/features/canvas/hooks/useChannelTasks";
import { useDashboards } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { getPrVisualIcon } from "@posthog/ui/features/git-interaction/prIcon";
import { usePrDetails } from "@posthog/ui/features/git-interaction/usePrDetails";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { track } from "@posthog/ui/shell/analytics";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { Text } from "@radix-ui/themes";
import { useNavigate } from "@tanstack/react-router";
import { type ReactNode, useCallback, useEffect, useMemo } from "react";

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
// than the full activity stream.
export function WebsiteChannelArtifacts({ channelId }: { channelId: string }) {
  const navigate = useNavigate();

  useEffect(() => {
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "view_artifacts",
      surface: "channel_artifacts",
      channel_id: channelId,
    });
  }, [channelId]);

  useSetHeaderContent(
    useMemo(() => <ChannelHeader channelId={channelId} />, [channelId]),
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
    <div className="h-full overflow-y-auto bg-gray-1">
      <div className="mx-auto w-full max-w-[680px] px-4 py-6">
        {items.length === 0 ? (
          <div className="flex flex-col items-center gap-1 py-24 text-center">
            <Text className="font-medium text-[14px] text-gray-12">
              No artifacts yet
            </Text>
            <Text className="text-[13px] text-gray-10">
              Canvases and pull requests from this channel's tasks show up here.
            </Text>
          </div>
        ) : (
          <div className="flex flex-col gap-0.5">
            {items.map((item) =>
              item.kind === "canvas" ? (
                <ArtifactRow
                  key={item.key}
                  accent="violet"
                  icon={iconForTemplate(item.templateId, {
                    size: 15,
                    className: "text-violet-9",
                  })}
                  title={item.title}
                  subtitle={`Canvas · ${formatRelativeTimeShort(item.ts)}`}
                  onClick={() => openCanvas(item.dashboardId)}
                />
              ) : (
                <PrArtifactRow
                  key={item.key}
                  title={item.title}
                  prUrl={item.prUrl}
                  ts={item.ts}
                  onClick={() => openPr(item.prUrl)}
                />
              ),
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// A PR artifact row. The PR's lifecycle state (open / draft / merged / closed)
// is fetched per-URL (deduped + cached by usePrDetails) so the icon and label
// reflect the live state.
function PrArtifactRow({
  title,
  prUrl,
  ts,
  onClick,
}: {
  title: string;
  prUrl: string;
  ts: number;
  onClick: () => void;
}) {
  const {
    meta: { state, merged, draft },
  } = usePrDetails(prUrl);
  const config = getPrVisualConfig(state ?? "open", merged, draft);
  const PrIcon = getPrVisualIcon(config.icon);
  const prNumber = parsePrNumber(prUrl);

  const subtitle = [
    prNumber ? `Pull request #${prNumber}` : "Pull request",
    // Only show the resolved state once we have it, to avoid a flash of "Open".
    state ? config.label : null,
    formatRelativeTimeShort(ts),
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <ArtifactRow
      accent={config.color}
      icon={
        <PrIcon
          size={15}
          weight="bold"
          style={{ color: `var(--${config.color}-9)` }}
        />
      }
      title={title}
      subtitle={subtitle}
      onClick={onClick}
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
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-gray-3"
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
        <span className="truncate text-[11px] text-gray-10 leading-tight">
          {subtitle}
        </span>
      </span>
      <CaretRightIcon
        size={14}
        className="shrink-0 text-gray-8 opacity-0 transition-opacity group-hover:opacity-100"
      />
    </button>
  );
}
