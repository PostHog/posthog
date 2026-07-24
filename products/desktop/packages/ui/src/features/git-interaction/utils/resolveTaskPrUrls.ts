import { mergePrUrls } from "@posthog/shared";

export interface TaskPrUrls {
  primaryUrl: string | null;
  otherUrls: string[];
}

export interface ResolveTaskPrUrlsInput {
  cloudUrls: string[];
  cachedUrls: string[];
  currentBranchUrl: string | null;
}

export function resolveTaskPrUrls({
  cloudUrls,
  cachedUrls,
  currentBranchUrl,
}: ResolveTaskPrUrlsInput): TaskPrUrls {
  const primaryUrl = cloudUrls[0] ?? cachedUrls[0] ?? currentBranchUrl ?? null;
  const otherUrls = mergePrUrls(
    cloudUrls,
    cachedUrls,
    currentBranchUrl ? [currentBranchUrl] : [],
  ).filter((url) => url !== primaryUrl);
  return { primaryUrl, otherUrls };
}
