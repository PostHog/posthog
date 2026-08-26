import { Terminal } from "@phosphor-icons/react";
import { compactHomePath } from "@posthog/shared";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { useChatThreadChrome } from "../chat-thread/chatThreadChrome";
import { ToolRow } from "./ToolRow";
import {
  ContentPre,
  getContentText,
  stripCodeFences,
  ToolTitle,
  type ToolViewProps,
  truncateText,
  useToolCallStatus,
} from "./toolCallUtils";

const ANSI_REGEX = new RegExp(`${String.fromCharCode(0x1b)}\\[[0-9;]*m`, "g");
const MAX_COMMAND_LENGTH = 120;

interface ExecuteRawInput {
  command?: string;
  description?: string;
}

export function ExecuteToolView({
  toolCall,
  turnCancelled,
  turnComplete,
  expanded = false,
}: ToolViewProps) {
  const { status, rawInput, content, title } = toolCall;
  const { isLoading, isFailed, wasCancelled } = useToolCallStatus(
    status,
    turnCancelled,
    turnComplete,
  );

  const executeInput = rawInput as ExecuteRawInput | undefined;
  const command = executeInput?.command ?? "";
  // Header text shown when there's no command to display: an explicit description, else the tool
  // call title. Guarantees the row is never label-less (the empty-marker bug) even for execute
  // tools whose rawInput carries no `command`.
  const headerText = executeInput?.description ?? (command ? undefined : title);

  // The command renders in both chromes but styled differently: the new thread shows it as plain
  // mono text carried by the ChatMarker title; the legacy thread keeps the bordered inline chip so
  // ConversationView is unchanged when the chat thread is toggled off.
  const chatChrome = useChatThreadChrome();

  const output = stripCodeFences(getContentText(content) ?? "").replace(
    ANSI_REGEX,
    "",
  );
  const hasOutput = output.trim().length > 0;

  const commandTooltip = (
    <span className="block max-w-md whitespace-pre-wrap break-all font-mono text-xs">
      {compactHomePath(command)}
    </span>
  );

  return (
    <ToolRow
      icon={Terminal}
      isLoading={isLoading}
      isFailed={isFailed}
      wasCancelled={wasCancelled}
      defaultOpen={expanded}
      content={hasOutput ? <ContentPre>{output}</ContentPre> : undefined}
    >
      {headerText && <ToolTitle>{headerText}</ToolTitle>}
      {command &&
        (chatChrome ? (
          <ToolTitle className="min-w-0 shrink truncate font-mono">
            <Tooltip content={commandTooltip}>
              <span className="block truncate">
                {truncateText(compactHomePath(command), MAX_COMMAND_LENGTH)}
              </span>
            </Tooltip>
          </ToolTitle>
        ) : (
          <ToolTitle className="min-w-0 shrink truncate">
            <Tooltip content={commandTooltip}>
              <span className="block truncate border border-border bg-gray-5 font-mono">
                {truncateText(compactHomePath(command), MAX_COMMAND_LENGTH)}
              </span>
            </Tooltip>
          </ToolTitle>
        ))}
    </ToolRow>
  );
}
