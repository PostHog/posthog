import { Robot } from "@phosphor-icons/react";
import { ToolRow } from "@posthog/ui/features/sessions/components/session-update/ToolRow";
import {
  ContentPre,
  getContentText,
  ToolTitle,
  type ToolViewProps,
  useToolCallStatus,
} from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";

type SpawnInput = {
  title?: string;
  description?: string;
  repository?: string;
  delegation_profile?: string;
  runtime_adapter?: string;
  model?: string;
  reasoning_effort?: string;
  wake_on?: string[];
};

function parseSpawnInput(rawInput: unknown): SpawnInput {
  if (rawInput && typeof rawInput === "object") return rawInput as SpawnInput;
  if (typeof rawInput !== "string") return {};
  try {
    const parsed = JSON.parse(rawInput);
    return parsed && typeof parsed === "object" ? (parsed as SpawnInput) : {};
  } catch {
    return {};
  }
}

export function TasksSpawnToolView({
  toolCall,
  turnCancelled,
  turnComplete,
  expanded = false,
}: ToolViewProps) {
  const { isLoading, isFailed, wasCancelled, isComplete } = useToolCallStatus(
    toolCall.status,
    turnCancelled,
    turnComplete,
  );
  const input = parseSpawnInput(toolCall.rawInput);
  const route = input.delegation_profile
    ? `${input.delegation_profile} profile`
    : [input.runtime_adapter, input.model, input.reasoning_effort]
        .filter(Boolean)
        .join(" · ");
  const wakeOn = input.wake_on?.length
    ? input.wake_on.join(", ")
    : "completion";
  const output = getContentText(toolCall.content)?.trim();

  return (
    <ToolRow
      icon={Robot}
      isLoading={isLoading}
      isFailed={isFailed}
      wasCancelled={wasCancelled}
      defaultOpen={expanded || !isComplete}
      content={
        <div className="space-y-3 p-3 text-sm">
          {input.description && (
            <div className="whitespace-pre-wrap text-foreground">
              {input.description}
            </div>
          )}
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-muted-foreground">
            {input.repository && (
              <>
                <dt>Repository</dt>
                <dd className="text-foreground">{input.repository}</dd>
              </>
            )}
            {route && (
              <>
                <dt>Capability</dt>
                <dd className="text-foreground">{route}</dd>
              </>
            )}
            <dt>Wake parent</dt>
            <dd className="text-foreground">{wakeOn}</dd>
          </dl>
          {output && <ContentPre>{output}</ContentPre>}
        </div>
      }
    >
      <ToolTitle>Spawn child task</ToolTitle>
      {input.title && (
        <ToolTitle>
          <span className="text-muted-foreground">{input.title}</span>
        </ToolTitle>
      )}
    </ToolRow>
  );
}
