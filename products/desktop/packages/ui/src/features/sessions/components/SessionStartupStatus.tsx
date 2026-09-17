import type { SessionStartupPhase } from "@posthog/core/sessions/sessionStartup";
import { cn } from "@posthog/quill";
import { Spinner } from "@posthog/ui/primitives/Spinner";

export type SessionStartupTarget = "cloud" | "local";

const TITLE: Record<SessionStartupTarget, string> = {
  local: "Starting local agent",
  cloud: "Starting cloud agent",
};

export function startupLabel(
  target: SessionStartupTarget,
  phase?: SessionStartupPhase,
): string {
  return target === "local" && phase === "setup_hooks"
    ? "Running repository setup"
    : TITLE[target];
}

export function SessionStartupStatus({
  label,
  className,
}: {
  label: string;
  className?: string;
}) {
  return (
    <output
      className={cn(
        "flex min-w-0 items-center gap-2 text-gray-11 text-sm",
        className,
      )}
    >
      <Spinner aria-hidden size="sm" className="shrink-0 text-accent-11" />
      <span className="shrink-0">{label}</span>
    </output>
  );
}
