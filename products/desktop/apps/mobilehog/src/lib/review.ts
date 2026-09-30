import type { Task } from "@posthog/shared/domain-types";

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

// The review endpoint reads the latest run's pr_url, so the menu does too.
export function taskPrUrl(task: Task | undefined): string | null {
  const url = task?.latest_run?.output?.pr_url;
  return typeof url === "string" && url.length > 0 ? url : null;
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
