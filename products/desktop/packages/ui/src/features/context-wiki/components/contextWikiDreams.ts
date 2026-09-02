export function firstSummaryLine(summary: string): string {
  for (const line of summary.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    return trimmed;
  }
  return "";
}
