import {
  ArrowSquareOutIcon,
  ChatCircleIcon,
  DownloadSimpleIcon,
  EyeIcon,
  PackageIcon,
  SlackLogoIcon,
} from "@phosphor-icons/react";
import type { ResourceComment } from "@posthog/api-client/posthog-client";
import type { ThreadTimelineRow } from "@posthog/core/canvas/threadTimeline";
import {
  Badge,
  Button,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { Task, TaskThreadMessage } from "@posthog/shared/domain-types";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import {
  buildRows,
  commentTargets,
} from "@posthog/ui/features/canvas/components/taskArtifactRows";
import { useTaskRuns } from "@posthog/ui/features/canvas/hooks/useTaskRuns";
import { canvasArtifactOpenHandler } from "@posthog/ui/features/canvas/utils/canvasArtifactNavigation";
import { openPrInReview } from "@posthog/ui/features/code-review/openPrInReview";
import { usePrArtifact } from "@posthog/ui/features/git-interaction/usePrArtifact";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { usePrComments } from "@posthog/ui/features/pr-review/usePrComments";
import { usePrReviewThreads } from "@posthog/ui/features/pr-review/usePrReviewThreads";
import { buildCommentThreads } from "@posthog/ui/features/sessions/components/commentViewTypes";
import { useCommentsForTargetsQuery } from "@posthog/ui/features/sessions/components/useComments";
import { useArtifactDownload } from "@posthog/ui/features/sessions/useArtifactDownload";
import { useCommentsEnabled } from "@posthog/ui/features/sessions/useCommentsEnabled";
import { FileIcon } from "@posthog/ui/primitives/FileIcon";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { formatFileSize } from "@posthog/ui/utils/formatFileSize";
import { type ReactNode, useMemo, useState } from "react";

const EMPTY_COMMENTS: ResourceComment[] = [];

function ArtifactListRow({
  icon,
  title,
  detail,
  external,
  onOpen,
  onOpenExternal,
  fileActions,
  onHoverStart,
}: {
  icon: ReactNode;
  title: string;
  detail?: ReactNode;
  external?: boolean;
  onOpen?: () => void;
  /** Renders a trailing button that leaves the app instead of opening the
   *  artifact in place. Absent when there is nowhere safe to send the user. */
  onOpenExternal?: () => void;
  fileActions?: {
    onDownload: () => void;
    downloading: boolean;
  };
  onHoverStart?: () => void;
}) {
  return (
    // overflow-hidden so each half's hover fill is clipped to the row's radius.
    <div className="flex w-full items-center overflow-hidden rounded-md border border-border bg-muted text-[13px]">
      <button
        type="button"
        onClick={onOpen}
        disabled={!onOpen}
        onPointerEnter={onHoverStart}
        onFocus={onHoverStart}
        className="flex min-w-0 flex-1 items-center gap-2 px-2.5 py-2 text-left transition-colors enabled:hover:bg-gray-3"
      >
        {icon}
        <span className="min-w-0 flex-1 truncate font-medium">{title}</span>
        {detail && (
          <span className="shrink-0 text-muted-foreground">{detail}</span>
        )}
        {external && (
          <ArrowSquareOutIcon size={12} className="shrink-0 text-gray-9" />
        )}
      </button>
      {onOpenExternal && (
        <button
          type="button"
          onClick={onOpenExternal}
          aria-label={`Open ${title} externally`}
          className="flex shrink-0 items-center self-stretch border-border border-l px-2 text-muted-foreground transition-colors hover:bg-gray-3 hover:text-foreground"
        >
          <ArrowSquareOutIcon size={12} />
        </button>
      )}
      {fileActions && onOpen && (
        <div className="flex shrink-0 items-center gap-0.5 border-border border-l px-1">
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  variant="default"
                  size="icon-sm"
                  aria-label={`View ${title}`}
                  onClick={onOpen}
                />
              }
            >
              <EyeIcon size={14} />
            </TooltipTrigger>
            <TooltipContent>View</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  variant="default"
                  size="icon-sm"
                  aria-label={`Download ${title}`}
                  disabled={fileActions.downloading}
                  onClick={fileActions.onDownload}
                />
              }
            >
              <DownloadSimpleIcon size={14} />
            </TooltipTrigger>
            <TooltipContent>Download</TooltipContent>
          </Tooltip>
        </div>
      )}
    </div>
  );
}

function PrRow({
  url,
  openInPlaceTaskId,
}: {
  url: string;
  openInPlaceTaskId?: string;
}) {
  const { safeUrl, title, stateLabel, Icon, iconColor } = usePrArtifact(url);

  const [countsWanted, setCountsWanted] = useState(false);
  const comments = usePrComments(countsWanted ? safeUrl : null);
  const threads = usePrReviewThreads(countsWanted ? safeUrl : null);

  const commentCount =
    (comments.data?.length ?? 0) +
    (threads.data ?? []).reduce(
      (sum, thread) => sum + thread.comments.length,
      0,
    );
  const detailParts = [
    stateLabel,
    comments.data || threads.data
      ? `${commentCount} ${commentCount === 1 ? "comment" : "comments"}`
      : null,
  ].filter(Boolean);

  return (
    <ArtifactListRow
      icon={
        <Icon
          size={14}
          weight="bold"
          className="shrink-0"
          style={{ color: iconColor }}
        />
      }
      title={title}
      detail={detailParts.join(" · ") || null}
      onHoverStart={() => setCountsWanted(true)}
      onOpen={
        safeUrl
          ? () =>
              openInPlaceTaskId
                ? openPrInReview(openInPlaceTaskId, safeUrl)
                : openExternalUrl(safeUrl)
          : undefined
      }
      onOpenExternal={safeUrl ? () => openExternalUrl(safeUrl) : undefined}
    />
  );
}

function CanvasRow({
  name,
  url,
  commentCount,
}: {
  name: string;
  url: string | null;
  commentCount: number;
}) {
  const open = canvasArtifactOpenHandler(url);
  return (
    <ArtifactListRow
      icon={iconForTemplate("", { size: 14, className: "text-violet-9" })}
      title={name}
      detail={
        commentCount > 0 ? (
          <Badge>
            <ChatCircleIcon />
            {commentCount}
          </Badge>
        ) : (
          "Canvas"
        )
      }
      onOpen={open}
    />
  );
}

function FileRow({
  taskId,
  runId,
  artifactId,
  name,
  size,
  commentCount,
}: {
  taskId: string;
  runId: string | null;
  artifactId: string | null;
  name: string;
  size: number | undefined;
  /** Supplied by the pane's single comments query so each row doesn't fetch. */
  commentCount: number;
}) {
  const openArtifactTab = usePanelLayoutStore((state) => state.openArtifactTab);
  const { download, downloadingId } = useArtifactDownload();
  const canOpen = !!runId && !!artifactId;
  const sizeLabel = formatFileSize(size);
  const onOpen = canOpen
    ? () => {
        openArtifactTab(taskId, {
          runId: runId as string,
          artifactId: artifactId as string,
          name,
        });
      }
    : undefined;
  const onDownload = canOpen
    ? () => {
        void download({
          taskId,
          runId: runId as string,
          artifactId: artifactId as string,
          name,
        });
      }
    : undefined;
  return (
    <ArtifactListRow
      icon={<FileIcon filename={name} size={14} />}
      title={name}
      detail={
        <div className="flex items-center gap-1.5">
          <span>{sizeLabel ? `File · ${sizeLabel}` : "File"}</span>
          {commentCount > 0 && (
            <Badge>
              <ChatCircleIcon />
              {commentCount}
            </Badge>
          )}
        </div>
      }
      onOpen={onOpen}
      fileActions={
        onDownload
          ? { onDownload, downloading: downloadingId === artifactId }
          : undefined
      }
    />
  );
}

export function TaskArtifactsList({
  task,
  timeline,
  canOpenInPlace,
}: {
  task: Task;
  timeline: ThreadTimelineRow<TaskThreadMessage>[];
  /** See `ActivityTimeline` — without the task's own view alongside, a PR has to
   *  open externally rather than into a review pane nobody is showing. */
  canOpenInPlace?: boolean;
}) {
  const commentsEnabled = useCommentsEnabled();
  const { runs } = useTaskRuns(task.id);
  const rows = useMemo(
    () => buildRows(task, timeline, runs),
    [task, timeline, runs],
  );
  // One query for every row's badge, so N resources cost one request rather
  // than one per row. The threads themselves live in the Comments tab.
  const targets = useMemo(() => commentTargets(rows), [rows]);
  const commentsQuery = useCommentsForTargetsQuery(targets, task.id, {
    enabled: commentsEnabled,
  });
  const comments = commentsEnabled
    ? (commentsQuery.data ?? EMPTY_COMMENTS)
    : EMPTY_COMMENTS;
  // Open threads only, so a row's badge agrees with what the Comments tab
  // shows on the same resource.
  const openCountByItem = useMemo(() => {
    const counts = new Map<string, number>();
    for (const thread of buildCommentThreads(comments)) {
      const itemId = thread.root.item_id;
      if (thread.resolved || !itemId) continue;
      counts.set(itemId, (counts.get(itemId) ?? 0) + 1);
    }
    return counts;
  }, [comments]);

  if (rows.length === 0) {
    return (
      <Empty className="h-full border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <PackageIcon size={18} />
          </EmptyMedia>
          <EmptyTitle>No artifacts yet</EmptyTitle>
          <EmptyDescription>
            Pull requests, canvases, and files produced while working on this
            task show up here.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <div className="flex flex-col gap-1.5 p-2">
      {rows.map((row) =>
        row.kind === "pr" ? (
          <PrRow
            key={row.key}
            url={row.url}
            openInPlaceTaskId={canOpenInPlace ? task.id : undefined}
          />
        ) : row.kind === "canvas" ? (
          <CanvasRow
            key={row.key}
            name={row.name}
            url={row.url}
            commentCount={
              row.dashboardId ? (openCountByItem.get(row.dashboardId) ?? 0) : 0
            }
          />
        ) : row.kind === "file" ? (
          <FileRow
            key={row.key}
            taskId={task.id}
            runId={row.runId}
            artifactId={row.artifactId}
            name={row.name}
            size={row.size}
            commentCount={
              row.artifactId ? (openCountByItem.get(row.artifactId) ?? 0) : 0
            }
          />
        ) : (
          <ArtifactListRow
            key={row.key}
            icon={<SlackLogoIcon size={14} className="shrink-0 text-gray-11" />}
            title="Slack thread"
            detail="External"
            external
            onOpen={() => openExternalUrl(row.url)}
          />
        ),
      )}
    </div>
  );
}
