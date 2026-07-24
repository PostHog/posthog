import type { ReportArtefact } from "./types";

export type ActivityArtefact = Extract<
  ReportArtefact,
  { type: "commit" | "task_run" }
>;

export function selectActivityArtefacts(
  artefacts: ReportArtefact[],
): ActivityArtefact[] {
  return artefacts
    .filter(
      (a): a is ActivityArtefact =>
        a.type === "commit" || a.type === "task_run",
    )
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
}

export function shortSha(sha: string): string {
  return sha.slice(0, 12);
}

const SIGNALS_TYPE_LABELS: Record<string, string> = {
  research: "Research",
  implementation: "Implementation",
  repo_selection: "Repo selection",
};

function humanizeIdentifier(value: string): string {
  const spaced = value.replace(/[_-]+/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function taskRunLabel(content: {
  product: string;
  type: string;
}): string {
  if (content.product === "signals") {
    return (
      SIGNALS_TYPE_LABELS[content.type] ?? humanizeIdentifier(content.type)
    );
  }
  return humanizeIdentifier(content.type);
}

export function attributionLabel(artefact: {
  created_by?: { first_name?: string; email: string } | null;
  task_id?: string | null;
}): string | null {
  if (artefact.created_by) {
    return artefact.created_by.first_name?.trim() || artefact.created_by.email;
  }
  if (artefact.task_id) {
    return "agent";
  }
  return null;
}

type DiffLineKind = "add" | "del" | "hunk" | "context";

interface DiffLine {
  text: string;
  kind: DiffLineKind;
}

export function parseDiffLines(diff: string): DiffLine[] {
  return diff
    .replace(/\n$/, "")
    .split("\n")
    .map((text) => {
      if (text.startsWith("+") && !text.startsWith("+++")) {
        return { text, kind: "add" as const };
      }
      if (text.startsWith("-") && !text.startsWith("---")) {
        return { text, kind: "del" as const };
      }
      if (text.startsWith("@@")) {
        return { text, kind: "hunk" as const };
      }
      return { text, kind: "context" as const };
    });
}
