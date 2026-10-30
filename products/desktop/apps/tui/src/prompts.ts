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
  // Claude Code's AskUserQuestion: the options only cover the first question, so each is asked in turn.
  questions?: AcpQuestion[];
}

export interface AcpQuestion {
  question: string;
  header?: string;
  options: { label: string; description?: string }[];
}

export type PromptReply =
  | { kind: "dialog"; response: RpcExtensionUIResponse }
  | {
      kind: "permission";
      requestId: string;
      decision: McpToolPermissionDecision;
    }
  | {
      kind: "acp";
      taskRunId: string;
      toolCallId: string;
      optionId: string;
      // Each question's picked label, by question; the tool reads these, not the option id.
      answers?: Record<string, string>;
      // What the user typed for an option that asks what to do instead.
      customInput?: string;
    };

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

// An option such as "No, and tell the agent what to do differently" takes its text from the composer.
export const wantsText = (prompt: AgentPrompt, index: number): boolean =>
  prompt.kind === "acp" &&
  (prompt.request.options[index]?._meta as { customInput?: boolean })
    ?.customInput === true;

// The questions a Claude Code prompt asks, or none for a plain permission.
export const questionsOf = (prompt: AgentPrompt): AcpQuestion[] =>
  prompt.kind === "acp" ? (prompt.request.questions ?? []) : [];

const FEEDBACK_PLACEHOLDER = "Type what to do instead, then press Enter";

// `step` is the question being asked, for a prompt with several; `draft` is the text typed for an option that takes some.
export function promptSheet(prompt: AgentPrompt, step = 0, draft = ""): Sheet {
  const questions = questionsOf(prompt);
  const question = questions[step];
  if (question)
    return {
      title: question.question,
      items: question.options.map(({ label, description }) => ({
        label,
        ...(description && { detail: description }),
      })),
      footer: `Enter to choose · Esc to skip${
        questions.length > 1 ? ` · ${step + 1} of ${questions.length}` : ""
      }`,
    };
  if (prompt.kind === "acp")
    return {
      title: prompt.request.title,
      items: prompt.request.options.map(({ name }, index) => ({
        label: name,
        ...(wantsText(prompt, index) && {
          input: { placeholder: FEEDBACK_PLACEHOLDER, text: draft },
        }),
      })),
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

// The answer is a chosen item's index, typed text, or null when the user dismissed the prompt. A question
// prompt's `answered` holds the questions picked so far; the reply carries them all, the next one included.
export function promptReply(
  prompt: AgentPrompt,
  answer: number | string | null,
  answered: Record<string, string> = {},
  customInput?: string,
): PromptReply {
  if (prompt.kind === "acp") {
    const { taskRunId, toolCallId, options } = prompt.request;
    const questions = questionsOf(prompt);
    const question = questions[Object.keys(answered).length];
    if (question && typeof answer === "number") {
      const answers = {
        ...answered,
        [question.question]: question.options[answer]?.label ?? "",
      };
      // The option ids only name the first question's choices.
      const first = questions[0].options.findIndex(
        ({ label }) => label === answers[questions[0].question],
      );
      return {
        kind: "acp",
        taskRunId,
        toolCallId,
        optionId: `option_${Math.max(0, first)}`,
        answers,
      };
    }
    const chosen =
      typeof answer === "number"
        ? options[answer]
        : options.find((option) => option.kind.startsWith("reject"));
    return {
      kind: "acp",
      taskRunId,
      toolCallId,
      optionId: (chosen ?? options[0]).optionId,
      ...(customInput && { customInput }),
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
