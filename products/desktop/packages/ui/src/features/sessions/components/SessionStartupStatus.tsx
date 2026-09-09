import type { SessionStartupPhase } from "@posthog/core/sessions/sessionStartup";
import { cn } from "@posthog/quill";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { AnimatePresence, motion } from "framer-motion";

export type SessionStartupTarget = "cloud" | "local";

const TITLE: Record<SessionStartupTarget, string> = {
  local: "Starting local agent",
  cloud: "Starting cloud agent",
};

function statusLabel(
  target: SessionStartupTarget,
  phase?: SessionStartupPhase,
): string {
  return target === "local" && phase === "setup_hooks"
    ? "Running repository setup"
    : TITLE[target];
}

export interface SessionStartupStatusProps {
  executionTarget: SessionStartupTarget;
  phase?: SessionStartupPhase;
  /** Overrides the target's default label, e.g. "Connecting to agent...". */
  label?: string;
  detail?: string;
  className?: string;
}

export function SessionStartupStatus({
  executionTarget,
  phase,
  label,
  detail,
  className,
}: SessionStartupStatusProps) {
  return (
    <output
      className={cn(
        "flex min-w-0 items-center gap-2 text-gray-11 text-sm",
        className,
      )}
    >
      <Spinner aria-hidden size="sm" className="shrink-0 text-accent-11" />
      <span className="shrink-0">
        {label ?? statusLabel(executionTarget, phase)}
      </span>
      <AnimatePresence initial={false}>
        {detail && (
          <motion.span
            animate={{ opacity: 1, width: "auto" }}
            className="truncate text-gray-10"
            exit={{ opacity: 0, width: 0 }}
            initial={{ opacity: 0, width: 0 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
          >
            {detail}
          </motion.span>
        )}
      </AnimatePresence>
    </output>
  );
}
