import { readPrUrls, type Task } from "@posthog/shared";

export interface StatusChip {
  label: string;
  // A pull request: clicking the chip opens it.
  url?: string;
  tone?: "open" | "draft" | "merged" | "closed";
}

const PR_STATES = {
  open: "Open",
  draft: "Draft",
  merged: "Merged",
  closed: "Closed",
} as const;

const repoName = (repository: string | null | undefined): string | null =>
  repository ? (repository.split("/").at(-1) ?? null) : null;

// Where a chat runs, its repository and its pull request, for the pane's title row.
// A new chat has no task yet, so it describes the cloud run it will start in `newChatRepository`.
export function statusChips(
  task: Task | undefined,
  newChatRepository: string | null,
): StatusChip[] {
  const run = task?.latest_run as
    | (Task["latest_run"] & {
        pr_url?: string | null;
        pr_state?: string | null;
      })
    | undefined;
  const chips: StatusChip[] = [
    { label: run?.environment === "local" ? "Local" : "Cloud" },
  ];
  const repo = repoName(task ? task.repository : newChatRepository);
  if (repo) chips.push({ label: repo });

  const url =
    run?.pr_url ||
    readPrUrls(run?.output as Record<string, unknown> | undefined)[0];
  const number = url && /\/pull\/(\d+)/.exec(url)?.[1];
  if (url && number) {
    const state =
      run?.pr_state && run.pr_state in PR_STATES
        ? (run.pr_state as keyof typeof PR_STATES)
        : "open";
    chips.push({ label: `${PR_STATES[state]} #${number}`, url, tone: state });
  }
  return chips;
}
