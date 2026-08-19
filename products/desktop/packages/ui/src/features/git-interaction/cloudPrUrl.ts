import { mergePrUrls, readPrSummaries, readPrUrls } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";

type CloudPrSession = { cloudOutput?: Record<string, unknown> | null };

export function resolveCloudPrUrls(
  task: Task | undefined,
  session: CloudPrSession | undefined,
): string[] {
  return mergePrUrls(
    readPrUrls(task?.latest_run?.output),
    readPrUrls(session?.cloudOutput),
  );
}

export function resolveCloudPrSummaries(
  task: Task | undefined,
  session: CloudPrSession | undefined,
): Record<string, string> {
  return {
    ...readPrSummaries(session?.cloudOutput),
    ...readPrSummaries(task?.latest_run?.output),
  };
}

export function resolveCloudPrUrl(
  task: Task | undefined,
  session: CloudPrSession | undefined,
): string | null {
  return resolveCloudPrUrls(task, session)[0] ?? null;
}
