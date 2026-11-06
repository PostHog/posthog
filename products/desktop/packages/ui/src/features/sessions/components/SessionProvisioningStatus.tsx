import { CaretDown } from "@phosphor-icons/react";
import { Button, cn } from "@posthog/quill";
import { useProvisioningStore } from "@posthog/ui/features/provisioning/store";
import { useEffect, useRef, useState } from "react";
import { SessionStartupStatus, startupLabel } from "./SessionStartupStatus";

export function SessionProvisioningStatus({
  taskId,
  executionTarget,
}: {
  taskId: string;
  executionTarget: "cloud" | "local";
}) {
  const lines = useProvisioningStore((s) => s.output[taskId]);
  const [open, setOpen] = useState(false);
  const logRef = useRef<HTMLPreElement>(null);
  const detail = lines?.findLast((line) => line.trim())?.trim();
  const hasLog = !!lines && lines.length > 0;

  useEffect(() => {
    const el = logRef.current;
    if (!open || !lines || !el) return;
    el.scrollTop = el.scrollHeight;
  }, [open, lines]);

  return (
    <div className="w-full min-w-0">
      <SessionStartupStatus
        label={startupLabel(executionTarget, "setup_hooks")}
      />
      <div className="min-w-0 pl-[22px]">
        {detail && (
          <p className="mt-0.5 mb-0 truncate text-gray-10 text-sm">{detail}</p>
        )}
        {hasLog && (
          <Button
            aria-expanded={open}
            className="mt-1"
            onClick={() => setOpen(!open)}
            size="xs"
            variant="link-muted"
          >
            <CaretDown
              className={cn("transition-transform", open && "rotate-180")}
              size={12}
            />
            {open ? "Hide log" : "Show log"}
          </Button>
        )}
        {open && hasLog && (
          <pre
            ref={logRef}
            className="mt-1 mb-0 max-h-40 w-full overflow-auto whitespace-pre-wrap break-words rounded-(--radius-2) border border-(--gray-a5) bg-(--color-surface) p-2 text-left font-[var(--code-font-family)] text-(--gray-12) text-[13px]"
          >
            {lines.join("\n")}
          </pre>
        )}
      </div>
    </div>
  );
}
