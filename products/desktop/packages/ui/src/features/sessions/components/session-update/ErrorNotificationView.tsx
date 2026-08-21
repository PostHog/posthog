import { CaretRightIcon, Warning } from "@phosphor-icons/react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
  cn,
} from "@posthog/quill";
import { serializeError } from "@posthog/ui/features/notifications/errorDetails";
import { CodeBlock } from "@posthog/ui/primitives/CodeBlock";
import { useMemo } from "react";

interface ErrorNotificationViewProps {
  errorType: string;
  message: string;
  payload?: unknown;
}

export function ErrorNotificationView({
  errorType,
  message,
  payload,
}: ErrorNotificationViewProps) {
  const isContextError = errorType === "invalid_request";
  const serializedPayload = useMemo(
    () => (payload === undefined ? null : serializeError(payload)),
    [payload],
  );

  return (
    <div
      role="alert"
      className={cn(
        "my-2 flex gap-2 rounded-md border p-2",
        isContextError
          ? "border-orange-6 bg-orange-2 text-orange-11"
          : "border-red-6 bg-red-2 text-red-11",
      )}
    >
      <Warning weight="fill" className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="font-medium text-sm">{message}</div>
        {isContextError && (
          <div className="mt-1 text-[13px]">
            Tip: Type <code>/compact</code> to compress the conversation
            history.
          </div>
        )}
        {serializedPayload !== null && (
          <Collapsible className="mt-1 min-w-0 bg-transparent hover:bg-transparent data-open:bg-transparent">
            <CollapsibleTrigger
              data-attr="agent-error-payload-toggle"
              className="group min-h-0 bg-transparent px-0 py-1 text-left text-xs hover:bg-transparent aria-expanded:bg-transparent"
            >
              <CaretRightIcon
                size={12}
                className="transition-transform group-aria-expanded:rotate-90"
              />
              Full error
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-1 max-h-80 overflow-auto rounded-md border border-border bg-muted p-2 text-default">
              <CodeBlock size="1">{serializedPayload}</CodeBlock>
            </CollapsibleContent>
          </Collapsible>
        )}
      </div>
    </div>
  );
}
