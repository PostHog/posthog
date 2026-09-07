import { mergePrUrls, readPrSummaries, readPrUrls } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import type { AgentSession } from "@posthog/ui/features/sessions/sessionStore";

export function resolveCloudPrUrls(
  task: Task | undefined,
  session: AgentSession | undefined,
): string[] {
  return mergePrUrls(
    readPrUrls(task?.latest_run?.output),
    readPrUrls(session?.cloudOutput),
  );
}

export function resolveCloudPrSummaries(
  task: Task | undefined,
  session: AgentSession | undefined,
): Record<string, string> {
  return {
    ...readPrSummaries(session?.cloudOutput),
    ...readPrSummaries(task?.latest_run?.output),
  };
}

export function resolveCloudPrUrl(
  task: Task | undefined,
  session: AgentSession | undefined,
): string | null {
  return resolveCloudPrUrls(task, session)[0] ?? null;
}
