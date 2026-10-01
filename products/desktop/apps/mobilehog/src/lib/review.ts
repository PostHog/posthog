import type { Schemas } from "@posthog/api-client";
import type { Task, TaskRun } from "@posthog/shared/domain-types";

export type PatchLineKind = "add" | "del" | "hunk" | "meta" | "context";

export interface PatchLine {
  kind: PatchLineKind;
  text: string;
}

// GitHub file patches start at the first hunk, so there are no ---/+++ file
// headers and every leading + or - is a changed line.
export function classifyPatchLine(line: string): PatchLineKind {
  if (line.startsWith("@@")) return "hunk";
  if (line.startsWith("+")) return "add";
  if (line.startsWith("-")) return "del";
  if (line.startsWith("\\")) return "meta";
  return "context";
}

export function parsePatch(patch: string): PatchLine[] {
  if (!patch) return [];
  const lines = patch.replace(/\r\n/g, "\n").split("\n");
  if (lines[lines.length - 1] === "") lines.pop();
  return lines.map((text) => ({ kind: classifyPatchLine(text), text }));
}

export function splitPath(filename: string): { dir: string; base: string } {
  const slash = filename.lastIndexOf("/");
  return {
    dir: filename.slice(0, slash + 1),
    base: filename.slice(slash + 1),
  };
}

const FILE_STATUS: Record<string, string> = {
  added: "Added",
  removed: "Deleted",
  modified: "Modified",
  renamed: "Renamed",
  copied: "Copied",
  changed: "Changed",
  unchanged: "Unchanged",
};

export function fileStatusLabel(status: string): string {
  return (
    FILE_STATUS[status] ?? status.charAt(0).toUpperCase() + status.slice(1)
  );
}

function outputPrUrl(
  output: Record<string, unknown> | null | undefined,
): string | null {
  const url = output?.pr_url;
  return typeof url === "string" && url.length > 0 ? url : null;
}

// The task response copies an earlier run's PR into a resumed run.
export function taskPrUrl(task: Task | undefined): string | null {
  return outputPrUrl(task?.latest_run?.output);
}

// The review endpoint reads only the latest run's own output, so the menu
// checks that run and not the PR the task response copies into it.
export function reviewPrUrl(
  task: Task | undefined,
  run: TaskRun | undefined,
): string | null {
  if (!taskPrUrl(task) || !run || run.id !== task?.latest_run?.id) return null;
  return outputPrUrl(run.output);
}

const CI_POLL_MS = 15_000;

export function ciRefetchInterval(
  review: Schemas.TaskReview | undefined,
): number | false {
  return review?.ci_status === "pending" ? CI_POLL_MS : false;
}

export function prFilesUrl(url: string): string {
  return `${url.replace(/\/+$/, "")}/files`;
}

const FALLBACK_ERROR = "Could not load this pull request.";

// The endpoint explains a missing PR or GitHub connection in `detail`.
export function reviewErrorMessage(error: unknown): string {
  if (!error || typeof error !== "object" || !("body" in error)) {
    return FALLBACK_ERROR;
  }
  const body = (error as { body: unknown }).body;
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string" && detail.length > 0) return detail;
  }
  return FALLBACK_ERROR;
}
