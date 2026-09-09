import type { SessionStartupPhase } from "@posthog/core/sessions/sessionStartup";
import { Spinner } from "@posthog/ui/primitives/Spinner";

export interface SessionStartupStatusProps {
  executionTarget: "cloud" | "local";
  phase?: SessionStartupPhase;
}

export function SessionStartupStatus({
  executionTarget,
  phase,
}: SessionStartupStatusProps) {
  const isSetup = executionTarget === "local" && phase === "setup_hooks";
  const title = isSetup
    ? "Running repository setup"
    : executionTarget === "local"
      ? "Starting local agent"
      : "Starting cloud agent";
  return (
    <output className="flex items-center gap-2 text-gray-11 text-sm">
      <Spinner aria-hidden size="sm" className="shrink-0 text-accent-11" />
      <span>{title}</span>
    </output>
  );
}
