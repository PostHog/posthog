import {
  CaretRightIcon,
  CheckCircle,
  StopCircle,
  XCircle,
} from "@phosphor-icons/react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@posthog/quill";
import { serializeError } from "@posthog/ui/features/notifications/errorDetails";
import { CodeBlock } from "@posthog/ui/primitives/CodeBlock";
import { useMemo } from "react";

interface TaskNotificationViewProps {
  status: "completed" | "failed" | "stopped";
  summary: string;
  payload?: unknown;
}

const statusConfig = {
  completed: {
    icon: <CheckCircle size={14} weight="fill" className="text-green-9" />,
    label: "Background task completed",
    borderColor: "border-green-6 dark:border-green-8",
  },
  failed: {
    icon: <XCircle size={14} weight="fill" className="text-red-9" />,
    label: "Background task failed",
    borderColor: "border-red-6 dark:border-red-8",
  },
  stopped: {
    icon: <StopCircle size={14} weight="fill" className="text-orange-9" />,
    label: "Background task stopped",
    borderColor: "border-orange-6 dark:border-orange-8",
  },
};

export function TaskNotificationView({
  status,
  summary,
  payload,
}: TaskNotificationViewProps) {
  const config = statusConfig[status];
  const serializedPayload = useMemo(
    () => (payload === undefined ? null : serializeError(payload)),
    [payload],
  );

  return (
    <div className={`my-1 border-l-2 py-1 pl-3 ${config.borderColor}`}>
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          {config.icon}
          <span className="font-medium text-[13px] text-gray-12">
            {config.label}
          </span>
        </div>
        {summary && <span className="text-[13px] text-gray-11">{summary}</span>}
        {serializedPayload !== null && (
          <Collapsible className="min-w-0 bg-transparent hover:bg-transparent data-open:bg-transparent">
            <CollapsibleTrigger
              data-attr="background-task-payload-toggle"
              className="group min-h-0 bg-transparent px-0 py-1 text-left text-xs hover:bg-transparent aria-expanded:bg-transparent"
            >
              <CaretRightIcon
                size={12}
                className="transition-transform group-aria-expanded:rotate-90"
              />
              {status === "failed" ? "Full error" : "Full payload"}
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-1 max-h-80 overflow-auto rounded-md border border-border bg-muted p-2">
              <CodeBlock size="1">{serializedPayload}</CodeBlock>
            </CollapsibleContent>
          </Collapsible>
        )}
      </div>
    </div>
  );
}
