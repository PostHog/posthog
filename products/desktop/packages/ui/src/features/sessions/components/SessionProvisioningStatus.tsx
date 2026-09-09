import { CaretDown } from "@phosphor-icons/react";
import { Button, cn } from "@posthog/quill";
import { useProvisioningStore } from "@posthog/ui/features/provisioning/store";
import { useState } from "react";
import { SessionStartupStatus } from "./SessionStartupStatus";

export function SessionProvisioningStatus({
  taskId,
  executionTarget,
}: {
  taskId: string;
  executionTarget: "cloud" | "local";
}) {
  const lines = useProvisioningStore((s) => s.output[taskId]);
  const [open, setOpen] = useState(false);
  const detail = lines?.at(-1)?.trim();

  return (
    <div className="w-full">
      <div className="flex w-full items-center justify-center gap-2">
        <SessionStartupStatus
          executionTarget={executionTarget}
          phase="setup_hooks"
          detail={detail}
        />
        {lines && lines.length > 0 && (
          <Button
            aria-expanded={open}
            className="shrink-0"
            onClick={() => setOpen(!open)}
            size="xs"
            variant="outline"
          >
            <CaretDown
              className={cn("transition-transform", open && "rotate-180")}
              size={12}
            />
            {open ? "Hide log" : "Show log"}
          </Button>
        )}
      </div>
      {open && lines && lines.length > 0 && (
        <pre className="mt-2 max-h-40 w-full overflow-auto whitespace-pre-wrap break-all rounded-(--radius-2) border border-(--gray-a5) bg-(--color-surface) p-2 text-left font-[var(--code-font-family)] text-(--gray-12) text-[13px]">
          {lines.join("\n")}
        </pre>
      )}
    </div>
  );
}
