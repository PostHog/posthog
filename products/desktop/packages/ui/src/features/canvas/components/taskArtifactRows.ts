import {
  getPostHogObjectArtifactMetadata,
  groupRunArtifactVersions,
  OUTPUT_ARTIFACT_TYPES,
  type PostHogObjectArtifactMetadata,
  parseRunArtifacts,
  type RunArtifact,
  type RunArtifactVersions,
} from "@posthog/core/canvas/runArtifactSchemas";
import type { ThreadTimelineRow } from "@posthog/core/canvas/threadTimeline";
import {
  type CommentTarget,
  commentTargetKey,
} from "@posthog/core/comments/anchors";
import { readPrUrls } from "@posthog/shared";
import type {
  Task,
  TaskRun,
  TaskThreadMessage,
} from "@posthog/shared/domain-types";
import { parseHttpsUrl, parseShareLink } from "@posthog/ui/utils/posthogLinks";

export type RunFile = RunArtifact & { runId: string };

export type ArtifactRow =
  | { kind: "pr"; key: string; url: string; ts: number }
  | {
      kind: "canvas";
      key: string;
      name: string;
      url: string | null;
      /** The canvas row id, the stable comment target (never the name). */
      dashboardId: string | null;
      ts: number;
    }
  | {
      kind: "file";
      key: string;
      artifactId: string | null;
      name: string;
      runId: string | null;
      size: number | undefined;
      group: RunArtifactVersions<RunFile>;
    }
  | {
      kind: "posthog_object";
      key: string;
      artifactId: string;
      name: string;
      runId: string;
      metadata: PostHogObjectArtifactMetadata;
      uploadedAt: string | undefined;
    }
  | { kind: "slack"; key: string; url: string };

/**
 * Somewhere a task's comment threads live. Artifacts and canvases come from the
 * task's rows; the task itself is always one, holding the threads that belong
 * to the work rather than to any single deliverable.
 */
export type CommentSource =
  | { kind: "file"; target: CommentTarget; name: string; runId: string | null }
  | {
      kind: "posthog_object";
      target: CommentTarget;
      name: string;
      runId: string;
    }
  | { kind: "canvas"; target: CommentTarget; name: string; url: string | null }
  | { kind: "task"; target: CommentTarget; name: string };

export function taskCommentTarget(taskId: string): CommentTarget {
  return { scope: "task", itemId: taskId };
}

export function commentSources(
  taskId: string,
  rows: ArtifactRow[],
): CommentSource[] {
  const sources: CommentSource[] = [
    { kind: "task", target: taskCommentTarget(taskId), name: "This task" },
  ];
  const seen = new Set<string>();
  for (const row of rows) {
    const target = targetForRow(row);
    if (!target || seen.has(commentTargetKey(target))) continue;
    seen.add(commentTargetKey(target));
    if (row.kind === "file") {
      sources.push({ kind: "file", target, name: row.name, runId: row.runId });
    } else if (row.kind === "posthog_object") {
      sources.push({
        kind: "posthog_object",
        target,
        name: row.name,
        runId: row.runId,
      });
    } else if (row.kind === "canvas") {
      sources.push({ kind: "canvas", target, name: row.name, url: row.url });
    }
  }
  return sources;
}

/** The canvas's stable row id, recovered from its share link. */
function canvasDashboardId(url: string | null): string | null {
  if (!url) return null;
  const parsed = parseHttpsUrl(url);
  const target = parsed ? parseShareLink(parsed.href) : null;
  if (target?.kind === "canvas") return target.dashboardId;

  // Local development emits http:// canvas links, which are deliberately not
  // valid external share links. Recover only the exact route's final id here;
  // this value is used for an access-checked API query, never for navigation.
  try {
    const localUrl = new URL(url);
    if (localUrl.protocol !== "http:") return null;
    const segments = localUrl.pathname.split("/").filter(Boolean);
    if (
      segments.length === 4 &&
      segments[0] === "code" &&
      segments[1] === "canvas"
    ) {
      return decodeURIComponent(segments[3]);
    }
  } catch {
    return null;
  }
  return null;
}

/** Where a row's comments live, or null when the row can't carry any. */
function targetForRow(row: ArtifactRow): CommentTarget | null {
  if (
    (row.kind === "file" || row.kind === "posthog_object") &&
    row.artifactId
  ) {
    return { scope: "task_artifact", itemId: row.artifactId };
  }
  if (row.kind === "canvas" && row.dashboardId) {
    return { scope: "desktop_canvas", itemId: row.dashboardId };
  }
  return null;
}

/**
 * Every commentable resource this task produced, once each. Artifacts and
 * canvases share the generic comments API, differing only by scope, so a pane
 * can hold one query over all of them — and two timeline messages naming the
 * same canvas must not fetch it twice.
 */
export function commentTargets(rows: ArtifactRow[]): CommentTarget[] {
  const byKey = new Map<string, CommentTarget>();
  for (const row of rows) {
    const target = targetForRow(row);
    if (target) byKey.set(commentTargetKey(target), target);
  }
  return [...byKey.values()];
}

function readRunOutputs(run: TaskRun): RunArtifact[] {
  return parseRunArtifacts(
    (run as { artifacts?: unknown }).artifacts,
    OUTPUT_ARTIFACT_TYPES,
  );
}

function readRunPostHogReferences(run: TaskRun): Array<{
  artifact: RunArtifact & { id: string; name: string };
  metadata: PostHogObjectArtifactMetadata;
}> {
  return parseRunArtifacts((run as { artifacts?: unknown }).artifacts, [
    "reference",
  ]).flatMap((artifact) => {
    const metadata = getPostHogObjectArtifactMetadata(artifact);
    return artifact.id && artifact.name && metadata
      ? [
          {
            artifact: { ...artifact, id: artifact.id, name: artifact.name },
            metadata,
          },
        ]
      : [];
  });
}

export function buildRows(
  task: Task,
  timeline: ThreadTimelineRow<TaskThreadMessage>[],
  runs: TaskRun[],
): ArtifactRow[] {
  const rows: ArtifactRow[] = [];
  const seenPrUrls = new Set<string>();

  const addPr = (url: string, key: string, ts: number) => {
    if (seenPrUrls.has(url)) return;
    seenPrUrls.add(url);
    rows.push({ kind: "pr", key, url, ts });
  };

  for (const row of timeline) {
    if (row.kind !== "artifact") continue;
    if (row.artifact.kind === "pr") {
      addPr(row.artifact.url, row.message.id, row.timestamp);
    } else {
      const url = row.artifact.url;
      rows.push({
        kind: "canvas",
        key: row.message.id,
        name: row.artifact.name,
        url,
        dashboardId: canvasDashboardId(url),
        ts: row.timestamp,
      });
    }
  }

  const allRuns =
    runs.length > 0 ? runs : task.latest_run ? [task.latest_run] : [];

  const files: RunFile[] = [];
  const postHogReferences = new Map<
    string,
    {
      artifact: RunArtifact & { id: string; name: string };
      metadata: PostHogObjectArtifactMetadata;
      runId: string;
    }
  >();
  for (const run of allRuns) {
    // Runs added straight from output have no announcing timeline message, so
    // the run's own updated_at is the closest stand-in for the PR's age.
    const runTs = Date.parse(run.updated_at) || 0;
    for (const outputPr of readPrUrls(run.output)) {
      addPr(outputPr, `output-pr:${outputPr}`, runTs);
    }
    files.push(
      ...readRunOutputs(run).map((file) => ({ ...file, runId: run.id })),
    );
    for (const reference of readRunPostHogReferences(run)) {
      const existing = postHogReferences.get(reference.artifact.id);
      const sourceMessageIds = [
        ...new Set([
          ...(existing?.metadata.source_message_ids ?? []),
          ...reference.metadata.source_message_ids,
        ]),
      ];
      const newest =
        existing &&
        (existing.artifact.uploaded_at ?? "") >=
          (reference.artifact.uploaded_at ?? "")
          ? existing
          : { ...reference, runId: run.id };
      postHogReferences.set(reference.artifact.id, {
        ...newest,
        metadata: {
          ...newest.metadata,
          source_message_ids: sourceMessageIds,
          occurrence_count: sourceMessageIds.length,
        },
      });
    }
  }
  for (const group of groupRunArtifactVersions(files)) {
    if (group.dismissed) continue;
    rows.push({
      kind: "file",
      key: `file:${group.name}`,
      artifactId: group.latest.id ?? null,
      name: group.name,
      runId: group.latest.runId,
      size: group.latest.size,
      group,
    });
  }

  for (const { artifact, metadata, runId } of postHogReferences.values()) {
    if (artifact.dismissed_at) continue;
    rows.push({
      kind: "posthog_object",
      key: `posthog-object:${artifact.id}`,
      artifactId: artifact.id,
      name: artifact.name,
      runId,
      metadata,
      uploadedAt: artifact.uploaded_at,
    });
  }

  const slackUrl = task.latest_run?.state?.slack_thread_url;
  if (typeof slackUrl === "string" && slackUrl) {
    rows.push({ kind: "slack", key: "slack-thread", url: slackUrl });
  }

  return rows;
}
