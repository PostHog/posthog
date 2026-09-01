import type { AnySignalReportArtefact } from "@posthog/shared/domain-types";

export type ActivityArtefact = Extract<
  AnySignalReportArtefact,
  { type: "commit" | "task_run" }
>;

export function selectActivityArtefacts(
  artefacts: AnySignalReportArtefact[],
): ActivityArtefact[] {
  return artefacts
    .filter(
      (artefact): artefact is ActivityArtefact =>
        artefact.type === "commit" || artefact.type === "task_run",
    )
    .sort((left, right) => left.created_at.localeCompare(right.created_at));
}

export function shortSha(sha: string): string {
  return sha.slice(0, 12);
}

export type DiffLineKind = "add" | "del" | "hunk" | "context";

export interface DiffLine {
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
      if (text.startsWith("@@")) return { text, kind: "hunk" as const };
      return { text, kind: "context" as const };
    });
}
