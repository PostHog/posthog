import {
  ArrowSquareOutIcon,
  PackageIcon,
  SlackLogoIcon,
} from "@phosphor-icons/react";
import {
  OUTPUT_ARTIFACT_TYPES,
  parseRunArtifacts,
  type RunArtifact,
} from "@posthog/core/canvas/runArtifactSchemas";
import type { ThreadTimelineRow } from "@posthog/core/canvas/threadTimeline";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { readPrUrls } from "@posthog/shared";
import type {
  Task,
  TaskRun,
  TaskThreadMessage,
} from "@posthog/shared/domain-types";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import { useTaskRuns } from "@posthog/ui/features/canvas/hooks/useTaskRuns";
import { openPrInReview } from "@posthog/ui/features/code-review/openPrInReview";
import { usePrArtifact } from "@posthog/ui/features/git-interaction/usePrArtifact";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { usePrComments } from "@posthog/ui/features/pr-review/usePrComments";
import { usePrReviewThreads } from "@posthog/ui/features/pr-review/usePrReviewThreads";
import { FileIcon } from "@posthog/ui/primitives/FileIcon";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { formatFileSize } from "@posthog/ui/utils/formatFileSize";
import { parseHttpsUrl, parseShareLink } from "@posthog/ui/utils/posthogLinks";
import { navigateToShareTarget } from "@posthog/ui/utils/shareLinks";
import { getPostHogUrl } from "@posthog/ui/utils/urls";
import { type ReactNode, useMemo, useState } from "react";

type ArtifactRow =
  | { kind: "pr"; key: string; url: string }
  | { kind: "canvas"; key: string; name: string; url: string | null }
  | {
      kind: "file";
      key: string;
      artifactId: string | null;
      name: string;
      runId: string | null;
      size: number | undefined;
    }
  | { kind: "slack"; key: string; url: string };

function readRunOutputs(run: TaskRun): RunArtifact[] {
  return parseRunArtifacts(
    (run as { artifacts?: unknown }).artifacts,
    OUTPUT_ARTIFACT_TYPES,
  );
}

function buildRows(
  task: Task,
  timeline: ThreadTimelineRow<TaskThreadMessage>[],
  runs: TaskRun[],
): ArtifactRow[] {
  const rows: ArtifactRow[] = [];
  const seenPrUrls = new Set<string>();

  const addPr = (url: string, key: string) => {
    if (seenPrUrls.has(url)) return;
    seenPrUrls.add(url);
    rows.push({ kind: "pr", key, url });
  };

  for (const row of timeline) {
    if (row.kind !== "artifact") continue;
    if (row.artifact.kind === "pr") {
      addPr(row.artifact.url, row.message.id);
    } else {
      rows.push({
        kind: "canvas",
        key: row.message.id,
        name: row.artifact.name,
        url: row.artifact.url,
      });
    }
  }

  const allRuns =
    runs.length > 0 ? runs : task.latest_run ? [task.latest_run] : [];

  // Re-uploading a file replaces it rather than adding a second one: agents
  // revise a deliverable and upload it again under the same name, so keeping
  // every copy would bury the current one under its own drafts.
  const newestByName = new Map<string, { file: RunArtifact; runId: string }>();
  for (const run of allRuns) {
    for (const outputPr of readPrUrls(run.output)) {
      addPr(outputPr, `output-pr:${outputPr}`);
    }
    for (const file of readRunOutputs(run)) {
      if (!file.name) continue;
      const previous = newestByName.get(file.name);
      const isNewer =
        !previous ||
        (file.uploaded_at ?? "") >= (previous.file.uploaded_at ?? "");
      if (isNewer) newestByName.set(file.name, { file, runId: run.id });
    }
  }
  for (const [name, { file, runId }] of newestByName) {
    rows.push({
      kind: "file",
      key: `file:${file.id ?? file.storage_path ?? name}`,
      artifactId: file.id ?? null,
      name,
      runId,
      size: file.size,
    });
  }

  const slackUrl = task.latest_run?.state?.slack_thread_url;
  if (typeof slackUrl === "string" && slackUrl) {
    rows.push({ kind: "slack", key: "slack-thread", url: slackUrl });
  }

  return rows;
}

function ArtifactListRow({
  icon,
  title,
  detail,
  external,
  onOpen,
  onOpenExternal,
  onHoverStart,
}: {
  icon: ReactNode;
  title: string;
  detail?: string | null;
  external?: boolean;
  onOpen?: () => void;
  /** Renders a trailing button that leaves the app instead of opening the
   *  artifact in place. Absent when there is nowhere safe to send the user. */
  onOpenExternal?: () => void;
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

function CanvasRow({ name, url }: { name: string; url: string | null }) {
  const parsed = url ? parseHttpsUrl(url) : null;
  const target = parsed ? parseShareLink(parsed.href) : null;
  const open =
    parsed && target
      ? () => {
          const currentPostHogUrl = getPostHogUrl("/");
          const currentPostHogOrigin = currentPostHogUrl
            ? parseHttpsUrl(currentPostHogUrl)?.origin
            : null;
          if (parsed.origin === currentPostHogOrigin) {
            navigateToShareTarget(target);
          } else {
            openExternalUrl(parsed.href);
          }
        }
      : undefined;
  return (
    <ArtifactListRow
      icon={iconForTemplate("", { size: 14, className: "text-violet-9" })}
      title={name}
      detail="Canvas"
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
}: {
  taskId: string;
  runId: string | null;
  artifactId: string | null;
  name: string;
  size: number | undefined;
}) {
  const openArtifactTab = usePanelLayoutStore((state) => state.openArtifactTab);
  const canOpen = !!runId && !!artifactId;
  const onOpen = canOpen
    ? () => {
        openArtifactTab(taskId, {
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
      detail={["File", formatFileSize(size)].filter(Boolean).join(" · ")}
      onOpen={onOpen}
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
  const { runs } = useTaskRuns(task.id);
  const rows = useMemo(
    () => buildRows(task, timeline, runs),
    [task, timeline, runs],
  );

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
          <CanvasRow key={row.key} name={row.name} url={row.url} />
        ) : row.kind === "file" ? (
          <FileRow
            key={row.key}
            taskId={task.id}
            runId={row.runId}
            artifactId={row.artifactId}
            name={row.name}
            size={row.size}
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
