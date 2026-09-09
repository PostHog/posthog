import type { SessionStartupPhase } from "@posthog/core/sessions/sessionStartup";
import { Spinner } from "@posthog/ui/primitives/Spinner";

export interface SessionStartupStatusProps {
  executionTarget: "cloud" | "local";
  phase?: SessionStartupPhase;
  showDetails?: boolean;
}

export function SessionStartupStatus({
  executionTarget,
  phase,
  showDetails = true,
}: SessionStartupStatusProps) {
  const isSetup = executionTarget === "local" && phase === "setup_hooks";
  const title = isSetup
    ? "Running repository setup"
    : executionTarget === "local"
      ? "Starting local agent"
      : "Starting cloud agent";
  const description = isSetup
    ? "Startup hooks are running. A new worktree can take longer the first time."
    : executionTarget === "local"
      ? "Connecting to the agent on this device."
      : "Connecting to your cloud runner.";

  return (
    <output className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <Spinner aria-hidden size="sm" className="shrink-0 text-accent-11" />
        <span className="font-medium text-sm">{title}</span>
      </div>
      {showDetails && (
        <span className="text-gray-11 text-sm">{description}</span>
      )}
    </output>
  );
}
