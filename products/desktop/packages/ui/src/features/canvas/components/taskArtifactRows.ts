import {
  OUTPUT_ARTIFACT_TYPES,
  parseRunArtifacts,
  type RunArtifact,
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
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { parseHttpsUrl, parseShareLink } from "@posthog/ui/utils/posthogLinks";
import { navigateToShareTarget } from "@posthog/ui/utils/shareLinks";
import { getPostHogUrl } from "@posthog/ui/utils/urls";

export type ArtifactRow =
  | { kind: "pr"; key: string; url: string }
  | {
      kind: "canvas";
      key: string;
      name: string;
      url: string | null;
      /** The canvas row id, the stable comment target (never the name). */
      dashboardId: string | null;
    }
  | {
      kind: "file";
      key: string;
      artifactId: string | null;
      name: string;
      runId: string | null;
    }
  | { kind: "slack"; key: string; url: string };

/**
 * Somewhere a task's comment threads live. Artifacts and canvases come from the
 * task's rows; the task itself is always one, holding the threads that belong
 * to the work rather than to any single deliverable.
 */
export type CommentSource =
  | { kind: "file"; target: CommentTarget; name: string; runId: string | null }
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
  return target?.kind === "canvas" ? target.dashboardId : null;
}

export function openCanvasFromUrl(
  url: string | null,
): (() => void) | undefined {
  const parsed = url ? parseHttpsUrl(url) : null;
  const target = parsed ? parseShareLink(parsed.href) : null;
  if (!parsed || !target) return undefined;
  return () => {
    const currentPostHogUrl = getPostHogUrl("/");
    const currentPostHogOrigin = currentPostHogUrl
      ? parseHttpsUrl(currentPostHogUrl)?.origin
      : null;
    if (parsed.origin === currentPostHogOrigin) {
      navigateToShareTarget(target);
    } else {
      openExternalUrl(parsed.href);
    }
  };
}

/** Where a row's comments live, or null when the row can't carry any. */
function targetForRow(row: ArtifactRow): CommentTarget | null {
  if (row.kind === "file" && row.artifactId) {
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

export function buildRows(
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
      const url = row.artifact.url;
      rows.push({
        kind: "canvas",
        key: row.message.id,
        name: row.artifact.name,
        url,
        dashboardId: canvasDashboardId(url),
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
    });
  }

  const slackUrl = task.latest_run?.state?.slack_thread_url;
  if (typeof slackUrl === "string" && slackUrl) {
    rows.push({ kind: "slack", key: "slack-thread", url: slackUrl });
  }

  return rows;
}
