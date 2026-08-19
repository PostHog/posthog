import { cn } from "@posthog/quill";
import type { ReactNode } from "react";

// Purely visual switch mirroring quill Switch's tokens: the whole card is the
// interactive control, and a real switch would nest a button inside a button.
function SwitchPill({ checked }: { checked: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        "relative inline-block h-4 w-7 shrink-0 rounded-full transition-colors",
        checked ? "bg-(--primary)" : "bg-(--input)",
      )}
    >
      <span
        className={cn(
          "absolute top-0.5 left-0.5 size-3 rounded-full transition-transform",
          checked
            ? "translate-x-3 bg-(--primary-foreground)"
            : "bg-(--background)",
        )}
      />
    </span>
  );
}

export type DeliveryIllustration =
  | "push"
  | "toast"
  | "dock-badge"
  | "dock-bounce";

function AppTile({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "relative size-8 rounded-[9px] border border-(--gray-7) bg-(--gray-5)",
        className,
      )}
    >
      <div className="absolute inset-x-2 top-2 h-1 rounded-full bg-(--gray-8)" />
      <div className="absolute top-4 left-2 h-1 w-3 rounded-full bg-(--gray-7)" />
    </div>
  );
}

function Illustration({ kind }: { kind: DeliveryIllustration }) {
  switch (kind) {
    case "push":
      return (
        <div className="relative h-full w-full overflow-hidden">
          <div className="absolute top-2.5 right-2.5 flex w-24 items-center gap-1.5 rounded-md border border-(--gray-6) bg-(--color-panel-solid) p-1.5 shadow-sm">
            <div className="size-4 shrink-0 rounded-[5px] bg-(--gray-6)" />
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <div className="h-1 w-3/4 rounded-full bg-(--gray-8)" />
              <div className="h-1 w-full rounded-full bg-(--gray-6)" />
            </div>
          </div>
        </div>
      );
    case "toast":
      return (
        <div className="relative flex h-full w-full items-center justify-center">
          <div className="relative h-12 w-24 rounded-md border border-(--gray-6) bg-(--color-panel-solid)">
            <div className="absolute top-1.5 left-1.5 flex gap-0.5">
              <div className="size-1 rounded-full bg-(--gray-7)" />
              <div className="size-1 rounded-full bg-(--gray-7)" />
            </div>
            <div className="absolute right-1.5 bottom-1.5 flex w-14 items-center gap-1 rounded-sm border border-(--gray-6) bg-(--gray-4) p-1">
              <div className="size-1.5 shrink-0 rounded-full bg-(--green-9)" />
              <div className="h-1 flex-1 rounded-full bg-(--gray-8)" />
            </div>
          </div>
        </div>
      );
    case "dock-badge":
      return (
        <div className="relative flex h-full w-full items-center justify-center">
          <div className="relative">
            <AppTile />
            <div
              className="absolute size-2.5 rounded-full border-(--gray-2) border-2 bg-(--red-9)"
              style={{ top: -4, right: -4 }}
            />
          </div>
        </div>
      );
    case "dock-bounce":
      return (
        <div className="relative flex h-full w-full items-center justify-center">
          <div className="flex flex-col items-center gap-1">
            <AppTile className="-translate-y-0.5" />
            <div className="flex items-center gap-1">
              <div className="h-0.5 w-2 rounded-full bg-(--gray-7)" />
              <div className="h-0.5 w-4 rounded-full bg-(--gray-8)" />
              <div className="h-0.5 w-2 rounded-full bg-(--gray-7)" />
            </div>
          </div>
        </div>
      );
  }
}

interface NotificationDeliveryCardProps {
  title: string;
  caption: ReactNode;
  illustration: DeliveryIllustration;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
}

export function NotificationDeliveryCard({
  title,
  caption,
  illustration,
  checked,
  onCheckedChange,
  disabled = false,
}: NotificationDeliveryCardProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={title}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        "flex cursor-pointer flex-col overflow-hidden rounded-(--radius-3) border border-(--gray-5) bg-(--color-panel-solid) p-0 text-left transition-colors hover:border-(--gray-8)",
        disabled && "cursor-not-allowed opacity-50",
      )}
    >
      <div
        className={cn(
          "h-16 w-full border-(--gray-4) border-b bg-(--gray-3) transition-opacity",
          !checked && "opacity-45",
        )}
      >
        <Illustration kind={illustration} />
      </div>
      <div className="flex w-full flex-1 items-start justify-between gap-2 px-2.5 py-2">
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="font-medium text-[12px] text-gray-12 leading-4">
            {title}
          </span>
          <span className="text-[11px] text-gray-10 leading-snug">
            {caption}
          </span>
        </div>
        <span className="mt-0.5">
          <SwitchPill checked={checked} />
        </span>
      </div>
    </button>
  );
}
