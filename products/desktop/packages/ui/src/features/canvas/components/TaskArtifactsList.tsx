import {
  ArrowSquareOutIcon,
  CaretDownIcon,
  ChatCircleIcon,
  DownloadSimpleIcon,
  PackageIcon,
  SlackLogoIcon,
} from "@phosphor-icons/react";
import type { ResourceComment } from "@posthog/api-client/posthog-client";
import {
  getPostHogObjectArtifactMetadata,
  type RunArtifactVersions,
  runArtifactVersionKey,
} from "@posthog/core/canvas/runArtifactSchemas";
import type { ThreadTimelineRow } from "@posthog/core/canvas/threadTimeline";
import {
  Badge,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import type { Task, TaskThreadMessage } from "@posthog/shared/domain-types";
import { useMeQuery } from "@posthog/ui/features/auth/useMeQuery";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import {
  buildRows,
  commentTargets,
  type RunFile,
} from "@posthog/ui/features/canvas/components/taskArtifactRows";
import { useTaskRuns } from "@posthog/ui/features/canvas/hooks/useTaskRuns";
import { canvasArtifactOpenHandler } from "@posthog/ui/features/canvas/utils/canvasArtifactNavigation";
import { openPrInReview } from "@posthog/ui/features/code-review/openPrInReview";
import { usePrArtifact } from "@posthog/ui/features/git-interaction/usePrArtifact";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { usePrComments } from "@posthog/ui/features/pr-review/usePrComments";
import { usePrReviewThreads } from "@posthog/ui/features/pr-review/usePrReviewThreads";
import { buildCommentThreads } from "@posthog/ui/features/sessions/components/commentViewTypes";
import { useCompletedArtifactUploads } from "@posthog/ui/features/sessions/components/countArtifactUploads";
import { useCommentsForTargetsQuery } from "@posthog/ui/features/sessions/components/useComments";
import { useSessionSelector } from "@posthog/ui/features/sessions/sessionStore";
import { useArtifactDownload } from "@posthog/ui/features/sessions/useArtifactDownload";
import {
  ArtifactCard,
  stopCardOpen,
} from "@posthog/ui/primitives/ArtifactCard";
import { FileIcon } from "@posthog/ui/primitives/FileIcon";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { formatFileSize } from "@posthog/ui/utils/formatFileSize";
import {
  getObjectKind,
  POSTHOG_OBJECT_ICON_COLOR,
} from "@posthog/ui/utils/objectKinds";
import { useMemo, useState } from "react";

const EMPTY_COMMENTS: ResourceComment[] = [];

interface CurrentUser {
  id?: number;
  first_name?: string | null;
}

function CommentCountBadge({ count }: { count: number }) {
  if (count === 0) return null;
  return (
    <Badge>
      <ChatCircleIcon />
      {count}
    </Badge>
  );
}

function PrRow({
  url,
  ts,
  openInPlaceTaskId,
}: {
  url: string;
  ts: number;
  openInPlaceTaskId?: string;
}) {
  const { safeUrl, title, stateLabel, Icon, iconColor } = usePrArtifact(url);
  const meta = [stateLabel, ts ? formatRelativeTimeShort(ts) : null]
    .filter(Boolean)
    .join(" · ");

  const [countsWanted, setCountsWanted] = useState(false);
  const comments = usePrComments(countsWanted ? safeUrl : null);
  const threads = usePrReviewThreads(countsWanted ? safeUrl : null);

  const prCommentCount =
    (comments.data?.length ?? 0) +
    (threads.data ?? []).reduce(
      (sum, thread) => sum + thread.comments.length,
      0,
    );

  return (
    <ArtifactCard
      icon={<Icon size={16} weight="bold" style={{ color: iconColor }} />}
      title={title}
      meta={meta}
      onHoverStart={() => setCountsWanted(true)}
      onOpen={
        safeUrl
          ? () =>
              openInPlaceTaskId
                ? openPrInReview(openInPlaceTaskId, safeUrl)
                : openExternalUrl(safeUrl)
          : undefined
      }
      actions={
        <>
          <CommentCountBadge count={prCommentCount} />
          {safeUrl && (
            <Button
              variant="default"
              size="icon-sm"
              aria-label={`Open ${title} externally`}
              onClick={(event) => {
                stopCardOpen(event);
                openExternalUrl(safeUrl);
              }}
            >
              <ArrowSquareOutIcon size={14} />
            </Button>
          )}
        </>
      }
    />
  );
}

function CanvasRow({
  name,
  url,
  ts,
  commentCount,
}: {
  name: string;
  url: string | null;
  ts: number;
  commentCount: number;
}) {
  const open = canvasArtifactOpenHandler(url);
  const meta = ts ? `Canvas · ${formatRelativeTimeShort(ts)}` : "Canvas";
  return (
    <ArtifactCard
      icon={iconForTemplate("", { size: 16, className: "text-amber-11" })}
      title={name}
      meta={meta}
      onOpen={open}
      actions={<CommentCountBadge count={commentCount} />}
    />
  );
}

function wasEditedByCurrentUser(
  artifact: RunFile,
  currentUserId: number | undefined,
): boolean {
  return (
    artifact.uploaded_by === "user" &&
    currentUserId !== undefined &&
    artifact.uploaded_by_user_id === currentUserId
  );
}

/** Who a version came from, named rather than described. */
function uploaderLabel(
  artifact: RunFile,
  currentUser: CurrentUser | undefined,
): string {
  if (artifact.uploaded_by !== "user") return "Agent";
  if (wasEditedByCurrentUser(artifact, currentUser?.id)) {
    return currentUser?.first_name?.trim() || "You";
  }
  return "Teammate";
}

/** Compact one-based version label: v1 is oldest, v{total} is newest. */
function versionShortLabel(index: number, total: number): string {
  return `v${total - index}`;
}

function fileVersionMenuLabel(
  artifact: RunFile,
  index: number,
  total: number,
  currentUser: CurrentUser | undefined,
): string {
  return [
    versionShortLabel(index, total),
    uploaderLabel(artifact, currentUser),
    artifact.uploaded_at ? formatRelativeTimeShort(artifact.uploaded_at) : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function FileRow({
  taskId,
  group,
  commentCount,
  currentUser,
}: {
  taskId: string;
  group: RunArtifactVersions<RunFile>;
  /** Supplied by the pane's single comments query so each row doesn't fetch. */
  commentCount: number;
  currentUser: CurrentUser | undefined;
}) {
  const openArtifactTab = usePanelLayoutStore((state) => state.openArtifactTab);
  const { download, downloadingId } = useArtifactDownload();
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const pickedIndex = group.versions.findIndex(
    (version) => runArtifactVersionKey(version) === selectedKey,
  );
  const newestVisibleIndex = group.versions.findIndex(
    (version) => !version.dismissed_at,
  );
  const selectedIndex =
    pickedIndex >= 0 ? pickedIndex : Math.max(newestVisibleIndex, 0);
  const selected = group.versions[selectedIndex] ?? group.latest;
  const canOpen = !!selected.id;
  const onOpen = canOpen
    ? () => {
        openArtifactTab(taskId, {
          runId: selected.runId,
          artifactId: selected.id as string,
          name: group.name,
        });
      }
    : undefined;
  const onDownload = canOpen
    ? () => {
        void download({
          taskId,
          runId: selected.runId,
          artifactId: selected.id as string,
          name: group.name,
        });
      }
    : undefined;
  const metaText = [
    uploaderLabel(selected, currentUser),
    selected.uploaded_at ? formatRelativeTimeShort(selected.uploaded_at) : null,
    formatFileSize(selected.size),
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <ArtifactCard
      icon={<FileIcon filename={group.name} size={18} />}
      title={group.name}
      meta={
        <>
          {metaText && <span className="truncate">{metaText}</span>}
          {group.versions.length > 1 && (
            <>
              {metaText && <span>·</span>}
              <DropdownMenu>
                <DropdownMenuTrigger
                  render={
                    <button
                      type="button"
                      aria-label={`Choose a version of ${group.name}`}
                      onClick={stopCardOpen}
                      className="flex shrink-0 cursor-pointer items-center gap-0.5 text-foreground"
                    >
                      {versionShortLabel(selectedIndex, group.versions.length)}
                      <CaretDownIcon size={10} />
                    </button>
                  }
                />
                {/* w-max: the default popup width tracks the anchor, and this
                    trigger is a couple of characters wide, so version labels
                    would be cut off. */}
                <DropdownMenuContent align="start" className="w-max">
                  {group.versions.map((version, index) => (
                    <DropdownMenuItem
                      key={runArtifactVersionKey(version)}
                      onClick={() =>
                        setSelectedKey(runArtifactVersionKey(version))
                      }
                    >
                      {fileVersionMenuLabel(
                        version,
                        index,
                        group.versions.length,
                        currentUser,
                      )}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            </>
          )}
        </>
      }
      onOpen={onOpen}
      actions={
        <>
          <CommentCountBadge count={commentCount} />
          {onDownload && (
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button
                    variant="default"
                    size="icon-sm"
                    aria-label={`Download ${group.name}`}
                    disabled={downloadingId === selected.id}
                    onClick={(event) => {
                      stopCardOpen(event);
                      onDownload();
                    }}
                  />
                }
              >
                <DownloadSimpleIcon size={14} />
              </TooltipTrigger>
              <TooltipContent>Download</TooltipContent>
            </Tooltip>
          )}
        </>
      }
    />
  );
}

function PostHogObjectRow({
  taskId,
  artifactId,
  runId,
  name,
  objectKind,
  occurrenceCount,
  uploadedAt,
  commentCount,
}: {
  taskId: string;
  artifactId: string;
  runId: string;
  name: string;
  objectKind: string;
  occurrenceCount: number;
  uploadedAt: string | undefined;
  commentCount: number;
}) {
  const openArtifactTab = usePanelLayoutStore((state) => state.openArtifactTab);
  const object = getObjectKind(objectKind);
  const ObjectIcon = object.icon;
  const meta = [
    object.kindLabel,
    occurrenceCount > 1 ? `Referenced ${occurrenceCount} times` : null,
    uploadedAt ? formatRelativeTimeShort(uploadedAt) : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <ArtifactCard
      icon={<ObjectIcon size={16} color={POSTHOG_OBJECT_ICON_COLOR} />}
      title={name}
      meta={meta}
      onOpen={() =>
        openArtifactTab(taskId, { runId, artifactId, name, objectKind })
      }
      actions={<CommentCountBadge count={commentCount} />}
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
  // A finished upload_artifact tool call re-keys the runs query, so a file
  // the agent just delivered shows up now rather than on the next poll.
  const events = useSessionSelector(task.id, (session) => session?.events);
  const completedUploads = useCompletedArtifactUploads(events ?? []);
  // Occurrence counts move without changing the entry count when a turn
  // re-cites an already registered object, so the key sums them too.
  const referenceRefreshKey = useSessionSelector(task.id, (session) =>
    (session?.cloudArtifacts ?? []).reduce((sum, artifact) => {
      const reference = getPostHogObjectArtifactMetadata(artifact);
      return reference ? sum + 1 + reference.occurrence_count : sum;
    }, 0),
  );
  const { runs } = useTaskRuns(task.id, completedUploads + referenceRefreshKey);
  const { data: currentUser } = useMeQuery();
  const rows = useMemo(
    () => buildRows(task, timeline, runs),
    [task, timeline, runs],
  );
  // One query for every row's badge, so N resources cost one request rather
  // than one per row. The threads themselves live in the Comments tab.
  const targets = useMemo(() => commentTargets(rows), [rows]);
  const commentsQuery = useCommentsForTargetsQuery(targets, task.id);
  const comments = commentsQuery.data ?? EMPTY_COMMENTS;
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
            ts={row.ts}
            openInPlaceTaskId={canOpenInPlace ? task.id : undefined}
          />
        ) : row.kind === "canvas" ? (
          <CanvasRow
            key={row.key}
            name={row.name}
            url={row.url}
            ts={row.ts}
            commentCount={
              row.dashboardId ? (openCountByItem.get(row.dashboardId) ?? 0) : 0
            }
          />
        ) : row.kind === "file" ? (
          <FileRow
            key={row.key}
            taskId={task.id}
            group={row.group}
            commentCount={
              row.artifactId ? (openCountByItem.get(row.artifactId) ?? 0) : 0
            }
            currentUser={currentUser}
          />
        ) : row.kind === "posthog_object" ? (
          <PostHogObjectRow
            key={row.key}
            taskId={task.id}
            artifactId={row.artifactId}
            runId={row.runId}
            name={row.name}
            objectKind={row.metadata.object_kind}
            occurrenceCount={row.metadata.occurrence_count}
            uploadedAt={row.uploadedAt}
            commentCount={openCountByItem.get(row.artifactId) ?? 0}
          />
        ) : (
          <ArtifactCard
            key={row.key}
            icon={<SlackLogoIcon size={16} className="text-gray-11" />}
            title="Slack thread"
            meta="External"
            onOpen={() => openExternalUrl(row.url)}
            actions={
              <Button
                variant="default"
                size="icon-sm"
                aria-label="Open Slack thread externally"
                onClick={(event) => {
                  stopCardOpen(event);
                  openExternalUrl(row.url);
                }}
              >
                <ArrowSquareOutIcon size={14} />
              </Button>
            }
          />
        ),
      )}
    </div>
  );
}
