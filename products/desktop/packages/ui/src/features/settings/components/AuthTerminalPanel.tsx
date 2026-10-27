import { Terminal } from "@posthog/ui/features/terminal/Terminal";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import type { ReactElement } from "react";

export type AuthTerminalStatus = "running" | "checking" | "done" | "failed";

export interface AuthTerminalConfig {
  command: string;
  cwd: string;
  additionalEnv: Record<string, string>;
  unsetEnv: string[];
}

interface AuthTerminalPanelProps {
  sessionId: string;
  commandLabel: string;
  status: AuthTerminalStatus;
  terminal: AuthTerminalConfig;
  onExit: (exitCode?: number) => void;
  onOutput?: (data: string) => void;
}

const SURFACE = {
  dark: { body: "#131316", chrome: "#1c1c21", text: "#e6e6e6" },
  light: { body: "#f2f3ee", chrome: "#e7e9e1", text: "#3a4036" },
} as const;

const PILL: Record<AuthTerminalStatus, { dot: string; label: string }> = {
  running: {
    dot: "animate-pulse bg-(--amber-9) motion-reduce:animate-none",
    label: "Running",
  },
  checking: {
    dot: "animate-pulse bg-(--gray-9) motion-reduce:animate-none",
    label: "Checking",
  },
  done: { dot: "bg-(--green-9)", label: "Done" },
  failed: { dot: "bg-(--red-9)", label: "Failed" },
};

export function AuthTerminalPanel({
  sessionId,
  commandLabel,
  status,
  terminal,
  onExit,
  onOutput,
}: AuthTerminalPanelProps): ReactElement {
  const isDarkMode = useThemeStore((state) => state.isDarkMode);
  const surface = isDarkMode ? SURFACE.dark : SURFACE.light;

  return (
    <div
      className="overflow-hidden rounded-(--radius-3) border border-border shadow-sm"
      style={{ backgroundColor: surface.body, color: surface.text }}
    >
      <div
        className="flex items-center justify-between border-black/10 border-b px-3 py-1.5"
        style={{ backgroundColor: surface.chrome }}
      >
        <span className="flex items-center gap-2 font-mono text-[11px] opacity-80">
          <span aria-hidden>❯</span>
          {commandLabel}
        </span>
        <span className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wide opacity-70">
          <span
            className={`inline-block h-1.5 w-1.5 rounded-full ${PILL[status].dot}`}
            aria-hidden
          />
          {PILL[status].label}
        </span>
      </div>
      <div className="h-72">
        <Terminal
          sessionId={sessionId}
          persistenceKey={sessionId}
          cwd={terminal.cwd}
          command={terminal.command}
          additionalEnv={terminal.additionalEnv}
          unsetEnv={terminal.unsetEnv}
          sensitive
          onExit={onExit}
          onOutput={onOutput}
        />
      </div>
    </div>
  );
}
