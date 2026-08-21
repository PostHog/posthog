import { compactHomePath } from "@posthog/shared";
import { ToolRow } from "./ToolRow";
import {
  ContentPre,
  compactInput,
  formatInput,
  getContentText,
  getFilename,
  iconForToolCall,
  stripCodeFences,
  ToolTitle,
  type ToolViewProps,
  useToolCallStatus,
} from "./toolCallUtils";

const toolNameDisplays: Record<
  string,
  { prefix: string; pastPrefix: string; suffix: string; inputKey: string }
> = {
  Skill: {
    prefix: "Reading",
    pastPrefix: "Read",
    suffix: "skill",
    inputKey: "skill",
  },
  ToolSearch: {
    prefix: "Searching",
    pastPrefix: "Searched",
    suffix: "tools",
    inputKey: "query",
  },
};

interface ToolCallViewProps extends ToolViewProps {
  agentToolName?: string;
}

export function ToolCallView({
  toolCall,
  turnCancelled,
  turnComplete,
  agentToolName,
  expanded = false,
}: ToolCallViewProps) {
  const { title, kind, status, locations, content, rawInput } = toolCall;
  const { isLoading, isFailed, wasCancelled, isComplete } = useToolCallStatus(
    status,
    turnCancelled,
    turnComplete,
  );
  const KindIcon = iconForToolCall(toolCall, agentToolName);

  const filePath = kind === "read" && locations?.[0]?.path;
  const toolDisplay = agentToolName
    ? toolNameDisplays[agentToolName]
    : undefined;
  const highlightValue =
    toolDisplay && rawInput && typeof rawInput === "object"
      ? (rawInput as Record<string, unknown>)[toolDisplay.inputKey]
      : undefined;
  const specialDisplay =
    toolDisplay && typeof highlightValue === "string"
      ? { ...toolDisplay, value: highlightValue }
      : undefined;

  // Reads back in past tense once the tool has finished ("Reading" → "Read").
  const displayText = specialDisplay
    ? isLoading
      ? specialDisplay.prefix
      : specialDisplay.pastPrefix
    : filePath
      ? `Read ${getFilename(filePath)}`
      : title
        ? compactHomePath(title)
        : undefined;

  const inputPreview = specialDisplay?.value ?? compactInput(rawInput);
  const fullInput = formatInput(rawInput);

  const output = stripCodeFences(getContentText(content) ?? "");
  const hasOutput = output.trim().length > 0;
  // Surface output for failures too, otherwise a failed call shows "(Failed)"
  // with no reason — the error text lives in `content`.
  const showOutput = (isComplete || isFailed) && hasOutput;

  const body =
    fullInput || showOutput ? (
      <>
        {fullInput && <ContentPre>{fullInput}</ContentPre>}
        {showOutput && <ContentPre>{output}</ContentPre>}
      </>
    ) : undefined;

  return (
    <ToolRow
      icon={KindIcon}
      isLoading={isLoading}
      isFailed={isFailed}
      wasCancelled={wasCancelled}
      defaultOpen={expanded}
      content={body}
    >
      {displayText && <ToolTitle>{displayText}</ToolTitle>}
      {inputPreview && (
        // `min-w-0 shrink` overrides the title's default `shrink-0`: the input preview is the
        // flexible piece of the header, so it gives way (and truncates) instead of overflowing.
        <ToolTitle className="min-w-0 shrink">
          <span className="font-mono text-primary text-sm">{inputPreview}</span>
        </ToolTitle>
      )}
      {specialDisplay && <ToolTitle>{specialDisplay.suffix}</ToolTitle>}
    </ToolRow>
  );
}
