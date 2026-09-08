import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useEffect, useRef } from "react";
import { useProvisioningStore } from "./store";

interface ProvisioningViewProps {
  taskId: string;
}

export function ProvisioningView({ taskId }: ProvisioningViewProps) {
  const lines = useProvisioningStore((s) => s.output[taskId]);
  const scrollRef = useRef<HTMLPreElement>(null);

  const text = (lines ?? []).join("\n");

  useEffect(() => {
    const el = scrollRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, []);

  return (
    <div className="h-full">
      <div className="flex h-full flex-col gap-2 p-3">
        <div className="flex items-center gap-2">
          <Spinner size={14} />
          <span className="font-medium text-[13px]">Loading</span>
        </div>
        <div className="min-h-0 flex-1 rounded-(--radius-2) border border-(--gray-a5) bg-(--color-surface)">
          <pre
            ref={scrollRef}
            className="m-0 h-full overflow-auto whitespace-pre-wrap break-all p-2 font-[var(--code-font-family)] text-(--gray-12) text-[13px]"
          >
            {text}
          </pre>
        </div>
      </div>
    </div>
  );
}
