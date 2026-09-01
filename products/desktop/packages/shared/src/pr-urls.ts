function dedupeNonEmpty(urls: readonly unknown[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const url of urls) {
    if (typeof url !== "string" || url.length === 0 || seen.has(url)) continue;
    seen.add(url);
    result.push(url);
  }
  return result;
}

export function readPrUrls(
  output: Record<string, unknown> | null | undefined,
): string[] {
  if (!output) return [];
  const listed = Array.isArray(output.pr_urls)
    ? dedupeNonEmpty(output.pr_urls)
    : [];
  const single = output.pr_url;
  if (typeof single === "string" && single.length > 0) {
    if (listed.length === 0) return [single];
    if (!listed.includes(single)) listed.push(single);
  }
  return listed;
}

export function mergePrUrls(
  ...lists: ReadonlyArray<readonly string[]>
): string[] {
  return dedupeNonEmpty(lists.flat());
}

export function promotePrUrl(urls: readonly string[], url: string): string[] {
  return dedupeNonEmpty([url, ...urls]);
}

export function readPrSummaries(
  output: Record<string, unknown> | null | undefined,
): Record<string, string> {
  const raw = output?.pr_summaries;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  const result: Record<string, string> = {};
  for (const [url, summary] of Object.entries(raw)) {
    if (typeof summary === "string" && summary.length > 0) {
      result[url] = summary;
    }
  }
  return result;
}

export function buildPrOutput(
  existing: Record<string, unknown> | null | undefined,
  urls: readonly string[],
  summaries?: Record<string, string>,
): Record<string, unknown> {
  const clean = dedupeNonEmpty(urls);
  const {
    pr_url: _prUrl,
    pr_urls: _prUrls,
    pr_summaries: _prSummaries,
    ...rest
  } = existing ?? {};
  if (clean.length === 0) return rest;

  const merged = { ...readPrSummaries(existing), ...summaries };
  const kept: Record<string, string> = {};
  for (const url of clean) {
    if (merged[url]) kept[url] = merged[url];
  }

  return {
    ...rest,
    pr_url: clean[0],
    pr_urls: clean,
    ...(Object.keys(kept).length > 0 ? { pr_summaries: kept } : {}),
  };
}
