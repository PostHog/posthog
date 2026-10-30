import type { PermissionOption } from "@agentclientprotocol/sdk";
import type { RpcExtensionUIResponse } from "@posthog/agent/pi/types";
import type { PiExtensionDialogRequest } from "@posthog/core/pi-runtime/piExtensionStore";
import type {
  McpToolPermissionDecision,
  McpToolPermissionRequest,
} from "@posthog/shared";
import { buildPiExtensionResponse } from "@posthog/ui/features/pi-sessions/piExtensionResponse";
import type { Sheet } from "./sheet";

// Something a local agent waits on the user for.
export type AgentPrompt =
  | { kind: "dialog"; request: PiExtensionDialogRequest }
  | { kind: "permission"; request: McpToolPermissionRequest }
  // Claude Code asking before a tool call, with the options it offers.
  | { kind: "acp"; request: AcpPermissionRequest };

export interface AcpPermissionRequest {
  taskRunId: string;
  toolCallId: string;
  title: string;
  options: PermissionOption[];
}

export type PromptReply =
  | { kind: "dialog"; response: RpcExtensionUIResponse }
  | {
      kind: "permission";
      requestId: string;
      decision: McpToolPermissionDecision;
    }
  | { kind: "acp"; taskRunId: string; toolCallId: string; optionId: string };

const PERMISSIONS: { label: string; decision: McpToolPermissionDecision }[] = [
  { label: "Allow once", decision: "allow" },
  { label: "Always allow", decision: "allow_always" },
  { label: "Reject", decision: "reject" },
];
const CONFIRM = ["Yes", "No"];
const CHOOSE = "Enter to choose · Esc to cancel";

export const promptId = (prompt: AgentPrompt): string =>
  prompt.kind === "dialog"
    ? prompt.request.id
    : prompt.kind === "acp"
      ? `${prompt.request.taskRunId}:${prompt.request.toolCallId}`
      : prompt.request.requestId;

// Input and editor prompts take their answer from the composer instead of a list.
export const takesText = (prompt: AgentPrompt): boolean =>
  prompt.kind === "dialog" &&
  (prompt.request.method === "input" || prompt.request.method === "editor");

export function promptSheet(prompt: AgentPrompt): Sheet {
  if (prompt.kind === "acp")
    return {
      title: prompt.request.title,
      items: prompt.request.options.map(({ name }) => ({ label: name })),
      footer: "Enter to choose · Esc to reject",
    };
  if (prompt.kind === "permission") {
    const { serverName, toolName, arguments: args } = prompt.request;
    return {
      title: `Allow ${toolName} from ${serverName}?`,
      description: JSON.stringify(args),
      items: PERMISSIONS.map(({ label }) => ({ label })),
      footer: "Enter to choose · Esc to reject",
    };
  }
  const { request } = prompt;
  if (request.method === "select")
    return {
      title: request.title,
      items: request.options.map((label) => ({ label })),
      footer: CHOOSE,
    };
  if (request.method === "confirm")
    return {
      title: request.title,
      description: request.message,
      items: CONFIRM.map((label) => ({ label })),
      footer: CHOOSE,
    };
  return {
    title: request.title,
    description: request.method === "input" ? request.placeholder : undefined,
    items: [],
    footer: "Type your answer below and press Enter · Esc to cancel",
  };
}

// The answer is a chosen item's index, typed text, or null when the user dismissed the prompt.
export function promptReply(
  prompt: AgentPrompt,
  answer: number | string | null,
): PromptReply {
  if (prompt.kind === "acp") {
    const { taskRunId, toolCallId, options } = prompt.request;
    const chosen =
      typeof answer === "number"
        ? options[answer]
        : options.find((option) => option.kind.startsWith("reject"));
    return {
      kind: "acp",
      taskRunId,
      toolCallId,
      optionId: (chosen ?? options[0]).optionId,
    };
  }
  if (prompt.kind === "permission")
    return {
      kind: "permission",
      requestId: prompt.request.requestId,
      decision:
        typeof answer === "number" ? PERMISSIONS[answer].decision : "reject",
    };
  const { request } = prompt;
  if (answer === null)
    return {
      kind: "dialog",
      response: {
        type: "extension_ui_response",
        id: request.id,
        cancelled: true,
      },
    };
  const value =
    typeof answer === "string"
      ? answer
      : request.method === "select"
        ? request.options[answer]
        : answer === 0;
  return { kind: "dialog", response: buildPiExtensionResponse(request, value) };
}
