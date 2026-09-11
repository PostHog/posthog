import type { SignalReportPriority } from "@posthog/shared/types";

const PRIORITY_CLASSES: Record<SignalReportPriority, string> = {
  P0: "bg-(--red-3) text-(--red-11) ring-1 ring-(--red-5) ring-inset",
  P1: "bg-(--orange-3) text-(--orange-11) ring-1 ring-(--orange-5) ring-inset",
  P2: "bg-(--amber-3) text-(--amber-11) ring-1 ring-(--amber-5) ring-inset",
  P3: "bg-(--gray-3) text-gray-11 ring-1 ring-(--gray-5) ring-inset",
  P4: "bg-(--gray-2) text-gray-10 ring-1 ring-(--gray-4) ring-inset",
};

interface PriorityMonogramProps {
  priority: SignalReportPriority | null | undefined;
  size?: "small" | "default" | "large";
}

const SIZE_CLASSES: Record<
  NonNullable<PriorityMonogramProps["size"]>,
  string
> = {
  small: "h-5 w-5 text-[8px]",
  default: "h-6 w-6 text-[9px]",
  large: "h-10 w-10 text-[12px]",
};

export function PriorityMonogram({
  priority,
  size = "default",
}: PriorityMonogramProps) {
  const label = priority ?? "–";
  const toneClass = priority
    ? PRIORITY_CLASSES[priority]
    : "bg-(--gray-2) text-(--gray-9)";

  return (
    <div
      className={[
        "flex shrink-0 items-center justify-center rounded-(--radius-1) font-bold tracking-tight",
        SIZE_CLASSES[size],
        toneClass,
      ].join(" ")}
      aria-label={priority ? `Priority ${priority}` : "Priority unknown"}
      role="img"
    >
      {label}
    </div>
  );
}
