import { INBOX_TRIAGE_ROUTE } from "@posthog/ui/features/inbox/triageRoute";
import { useNavigate } from "@tanstack/react-router";
import { useEffect } from "react";

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    target.tagName === "INPUT" ||
    target.tagName === "TEXTAREA" ||
    target.tagName === "SELECT"
  );
}

/** "t" from the reports list or an open report starts triage. */
export function useInboxTriageHotkey(options: {
  enabled: boolean;
  triageReportCount?: number;
}): void {
  const { enabled, triageReportCount } = options;
  const navigate = useNavigate();

  useEffect(() => {
    if (!enabled || triageReportCount === 0) return;
    const onKeyDown = (event: KeyboardEvent): void => {
      if (isTypingTarget(event.target)) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key.toLowerCase() !== "t") return;
      event.preventDefault();
      void navigate({ to: INBOX_TRIAGE_ROUTE });
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [enabled, navigate, triageReportCount]);
}
