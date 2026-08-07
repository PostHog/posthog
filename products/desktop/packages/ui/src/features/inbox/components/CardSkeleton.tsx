interface CardSkeletonProps {
  /** Number of rows to render. */
  count?: number;
  /** Row style: bordered rows joined into a list, or freestanding cards. */
  variant?: "rows" | "cards";
}

export function CardSkeleton({
  count = 4,
  variant = "rows",
}: CardSkeletonProps) {
  if (variant === "cards") {
    return (
      <div className="flex flex-col gap-3">
        {Array.from({ length: count }).map((_, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: static skeleton row
          <SkeletonRow key={i} rounded />
        ))}
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-(--radius-2) border border-(--gray-5) bg-(--color-panel-solid)">
      {Array.from({ length: count }).map((_, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: static skeleton row
        <SkeletonRow key={i} bordered />
      ))}
    </div>
  );
}

function SkeletonRow({
  rounded,
  bordered,
}: {
  rounded?: boolean;
  bordered?: boolean;
}) {
  return (
    <div
      className={[
        "flex w-full items-stretch gap-3 px-4 py-3.5",
        rounded
          ? "rounded-(--radius-2) border border-border bg-(--color-panel-solid)"
          : bordered
            ? "border-(--gray-5) border-b last:border-b-0"
            : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <span className="h-8 w-8 shrink-0 animate-pulse rounded-(--radius-2) bg-(--gray-3)" />
      <div className="flex min-w-0 flex-1 flex-col gap-2 py-0.5">
        <span className="h-3.5 w-3/5 animate-pulse rounded bg-(--gray-3)" />
        <span className="h-3 w-4/5 animate-pulse rounded bg-(--gray-2)" />
        <div className="flex items-center gap-1.5 pt-0.5">
          <span className="h-3.5 w-16 animate-pulse rounded bg-(--gray-3)" />
          <span className="h-3.5 w-20 animate-pulse rounded bg-(--gray-3)" />
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2 self-center">
        <span className="h-3 w-10 animate-pulse rounded bg-(--gray-3)" />
        <span className="h-7 w-16 animate-pulse rounded-(--radius-2) bg-(--gray-3)" />
      </div>
    </div>
  );
}
