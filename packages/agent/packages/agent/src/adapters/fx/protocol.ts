import {
  type ContentBlock,
  RequestError,
  type RequestPermissionRequest,
  type SessionConfigOption,
  type SessionModeState,
  type StopReason,
  type Usage,
} from "@agentclientprotocol/sdk";
import { readMcpToolDescriptor } from "@posthog/agent-contracts";
import { resourceLinkText } from "../codex-app-server/input";
import {
  classifyAgentError,
  sanitizeAgentErrorCause,
} from "../error-classification";
import { isLocalSkillCommandChunk } from "../local-skill";

export type FxPosthogMode = "default" | "full-access";

export const FX_ASK_MODE = "ask";

export const FX_POSTHOG_MODES: SessionModeState["availableModes"] = [
  {
    id: "default",
    name: "Ask",
    description: "Asks before each edit or command",
  },
  {
    id: "full-access",
    name: "Full access",
    description: "Auto-approves all operations",
  },
];

export function toFxPosthogMode(mode: unknown): FxPosthogMode | null {
  if (mode === "default" || mode === "full-access") return mode;
  if (mode === "bypassPermissions") return "full-access";
  if (mode === "auto" || mode === "acceptEdits") return "default";
  return null;
}

export function withPosthogMode(
  options: SessionConfigOption[] | null | undefined,
  mode: FxPosthogMode,
): SessionConfigOption[] {
  return (options ?? []).map((option) =>
    option.id === "mode" && option.type === "select"
      ? {
          ...option,
          currentValue: mode,
          options: FX_POSTHOG_MODES.map(({ id, name, description }) => ({
            value: id,
            name,
            description,
          })),
        }
      : option,
  );
}

interface FxToolCallMeta {
  fx?: { toolCall?: { mcp?: { server?: unknown; tool?: unknown } } };
}

export function fxMcpDescriptor(
  meta: unknown,
): { server: string; tool: string } | null {
  const mcp = (meta as FxToolCallMeta | null | undefined)?.fx?.toolCall?.mcp;
  return typeof mcp?.server === "string" && typeof mcp.tool === "string"
    ? { server: mcp.server, tool: mcp.tool }
    : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function withShellCommand(rawInput: unknown): unknown {
  if (!isRecord(rawInput) || typeof rawInput.command === "string") {
    return rawInput;
  }
  const request = rawInput.request;
  return isRecord(request) && typeof request.command === "string"
    ? { ...rawInput, command: request.command }
    : rawInput;
}

export function toPosthogPermissionRequest(
  params: RequestPermissionRequest,
  mcp: { server: string; tool: string } | null,
): RequestPermissionRequest {
  const { toolCall } = params;
  return {
    ...params,
    options: params.options.filter((option) => option.kind !== "allow_always"),
    toolCall: {
      ...toolCall,
      ...(toolCall.kind === "execute" && {
        rawInput: withShellCommand(toolCall.rawInput),
      }),
      _meta: withPosthogToolMeta(toolCall._meta, toolCall.kind, mcp),
    },
  };
}

interface FxPromptMeta {
  prContext?: unknown;
  localSkillContext?: unknown;
  localSkillName?: unknown;
}

export function toFxPrompt(
  prompt: ContentBlock[],
  meta: FxPromptMeta | null | undefined,
): ContentBlock[] {
  let blocks = prompt.map(
    (block): ContentBlock =>
      block.type === "resource_link"
        ? { type: "text", text: resourceLinkText(block.uri) }
        : block,
  );
  const skillContext =
    typeof meta?.localSkillContext === "string" ? meta.localSkillContext : null;
  if (skillContext) {
    const skillName =
      typeof meta?.localSkillName === "string" ? meta.localSkillName : null;
    const commandIndex = skillName
      ? blocks.findIndex((block) => isLocalSkillCommandChunk(block, skillName))
      : -1;
    if (commandIndex >= 0) {
      blocks = blocks.filter((_block, index) => index !== commandIndex);
    }
    blocks = [{ type: "text", text: skillContext }, ...blocks];
  }
  const prContext =
    typeof meta?.prContext === "string" && meta.prContext.length > 0
      ? meta.prContext
      : null;
  return prContext ? [{ type: "text", text: prContext }, ...blocks] : blocks;
}

export function gatewayFailureError(
  message: string,
  usage: Usage | null,
): RequestError {
  const classification = classifyAgentError(message);
  return new RequestError(-32603, message, {
    classification,
    result: sanitizeAgentErrorCause(message, classification),
    // fx keeps the prompt in its history, so a retry continues the turn instead of resending it.
    madeProgress: true,
    ...(usage && { usage }),
  });
}

export function withPosthogToolMeta(
  meta: Record<string, unknown> | null | undefined,
  kind: string | null | undefined,
  mcp: { server: string; tool: string } | null,
): Record<string, unknown> | undefined {
  if (mcp && !readMcpToolDescriptor(meta)) {
    const posthog =
      typeof meta?.posthog === "object" && meta.posthog !== null
        ? meta.posthog
        : {};
    return { ...meta, posthog: { ...posthog, mcp } };
  }
  if (kind === "execute") {
    return { ...meta, toolName: "Bash" };
  }
  return meta ?? undefined;
}

const FX_STOP_REASONS: Record<string, StopReason> = {
  end_turn: "end_turn",
  cancelled: "cancelled",
  max_output_tokens: "max_tokens",
  max_model_turns: "max_turn_requests",
  refused: "refusal",
};

export function fromFxStopReason(stopReason: string): StopReason {
  return FX_STOP_REASONS[stopReason] ?? "end_turn";
}

interface FxUsage {
  inputTokens?: number;
  outputTokens?: number;
  cacheReadTokens?: number;
  cacheWriteTokens?: number;
  reasoningTokens?: number;
}

export function fromFxUsage(usage: unknown): Usage | null {
  if (typeof usage !== "object" || usage === null) return null;
  const fx = usage as FxUsage;
  const inputTokens = fx.inputTokens ?? 0;
  const outputTokens = fx.outputTokens ?? 0;
  const cachedReadTokens = fx.cacheReadTokens ?? 0;
  const cachedWriteTokens = fx.cacheWriteTokens ?? 0;
  const totalTokens =
    inputTokens + outputTokens + cachedReadTokens + cachedWriteTokens;
  if (totalTokens === 0) return null;
  return {
    inputTokens,
    outputTokens,
    cachedReadTokens,
    cachedWriteTokens,
    thoughtTokens: fx.reasoningTokens ?? 0,
    totalTokens,
  };
}
