import { readPrUrls } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import {
  type PrStateDetails,
  usePrDetailsMap,
  usePrTitles,
} from "@posthog/ui/features/git-interaction/usePrDetails";
import { parseHttpsUrl } from "@posthog/ui/utils/posthogLinks";
import { useMemo } from "react";

export interface SpacePullRequest {
  url: string;
  task: Task;
  details: PrStateDetails | undefined;
  title: string | undefined;
}

const MAX_PULL_REQUESTS = 30;

export function useSpacePullRequests(tasks: Task[]): SpacePullRequest[] {
  const sources = useMemo(() => {
    const seen = new Set<string>();
    const out: { url: string; task: Task }[] = [];
    const byActivity = [...tasks].sort(
      (a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at),
    );
    for (const task of byActivity) {
      for (const raw of readPrUrls(task.latest_run?.output)) {
        if (out.length >= MAX_PULL_REQUESTS) return out;
        const parsed = parseHttpsUrl(raw);
        const url =
          parsed?.origin === "https://github.com" ? parsed.href : null;
        if (!url || seen.has(url)) continue;
        seen.add(url);
        out.push({ url, task });
      }
    }
    return out;
  }, [tasks]);
  const urls = useMemo(() => sources.map((entry) => entry.url), [sources]);
  const details = usePrDetailsMap(urls);
  const titles = usePrTitles(urls);
  return useMemo(
    () =>
      sources.map((source) => ({
        ...source,
        details: details[source.url],
        title: titles[source.url],
      })),
    [sources, details, titles],
  );
}
