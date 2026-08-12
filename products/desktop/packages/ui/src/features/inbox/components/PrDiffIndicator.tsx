export interface PrDiffIndicatorProps {
  added: number;
  removed: number;
  files?: number;
  className?: string;
}

export function hasVisibleDiffStats(added: number, removed: number): boolean {
  return added > 0 || removed > 0;
}

export function PrDiffIndicator({
  added,
  removed,
  files,
  className = "",
}: PrDiffIndicatorProps) {
  if (!hasVisibleDiffStats(added, removed)) {
    return null;
  }

  const fileLabel =
    files != null
      ? `${files} file${files === 1 ? "" : "s"} changed`
      : undefined;

  return (
    <span
      className={`flex shrink-0 items-center gap-1.5 font-mono text-[12px] tabular-nums ${className}`}
      title={fileLabel}
    >
      {added > 0 && (
        <span className="font-medium text-(--green-11)">+{added}</span>
      )}
      {removed > 0 && (
        <span className="font-medium text-(--red-11)">−{removed}</span>
      )}
    </span>
  );
}
