import { getPostHogExecDisplay } from "@posthog/core/sessions/posthogExecDisplay";
import {
  compactHomePath,
  formatPiMcpToolName,
  readMcpProxyCallDetails,
  readMcpToolDescriptor,
  readPiMcpCallDetails,
} from "@posthog/shared";
import type { ToolCall } from "@posthog/ui/features/sessions/types";
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

function mcpProxyDisplay(
  toolCall: ToolCall,
): { title: string; input?: string } | undefined {
  const details =
    readPiMcpCallDetails(toolCall.details) ??
    readMcpProxyCallDetails(toolCall._meta);
  if (details?.kind === "search") {
    return { title: "Search MCP tools", input: details.query };
  }
  if (details?.kind === "tool") {
    const posthogDisplay = getPostHogExecDisplay({
      tool: details.name,
      args: details.args,
    });
    const descriptor = readMcpToolDescriptor(toolCall._meta);
    const label = posthogDisplay?.label ?? descriptor?.title;
    if (label) {
      return {
        title: formatPiMcpToolName(details.name, label),
        ...(posthogDisplay?.input ? { input: posthogDisplay.input } : {}),
      };
    }
    return { title: formatPiMcpToolName(details.name) };
  }
  const descriptor = readMcpToolDescriptor(toolCall._meta);
  if (descriptor) {
    return {
      title: formatPiMcpToolName(
        `mcp__${descriptor.server}__${descriptor.tool}`,
        descriptor.title,
      ),
    };
  }
  if (toolCall.title.startsWith("mcp_")) {
    return { title: formatPiMcpToolName(toolCall.title) };
  }
  if (toolCall.title === "mcp") {
    return { title: "MCP" };
  }
  return undefined;
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
  const mcpDisplay = mcpProxyDisplay(toolCall);

  const displayText =
    mcpDisplay?.title ??
    (specialDisplay
      ? isLoading
        ? specialDisplay.prefix
        : specialDisplay.pastPrefix
      : filePath
        ? `Read ${getFilename(filePath)}`
        : title
          ? compactHomePath(title)
          : undefined);

  const inputPreview = mcpDisplay
    ? mcpDisplay.input
    : (specialDisplay?.value ?? compactInput(rawInput));
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
