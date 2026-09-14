import { compactHomePath } from "@posthog/shared";
import { useChatThreadChrome } from "../chat-thread/chatThreadChrome";
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
  // Chat-thread chrome drops the input/output divider because ContentPre carries its own border.
  // The standalone fallback retains the divider when chat-thread chrome is unavailable.
  const chatChrome = useChatThreadChrome();

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

  // Chat-thread chrome uses a past-tense prefix after a tool finishes. The standalone fallback
  // retains the present-tense prefix when chat-thread chrome is unavailable.
  const displayText = specialDisplay
    ? chatChrome && !isLoading
      ? specialDisplay.pastPrefix
      : specialDisplay.prefix
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
        {showOutput &&
          (chatChrome ? (
            <ContentPre>{output}</ContentPre>
          ) : (
            <div className={fullInput ? "border-gray-6 border-t" : undefined}>
              <ContentPre>{output}</ContentPre>
            </div>
          ))}
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
          <span
            className={
              chatChrome
                ? "font-mono text-primary text-sm"
                : "font-mono text-accent-11"
            }
          >
            {inputPreview}
          </span>
        </ToolTitle>
      )}
      {specialDisplay && <ToolTitle>{specialDisplay.suffix}</ToolTitle>}
    </ToolRow>
  );
}
