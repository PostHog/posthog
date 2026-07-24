import type {
  AssistantMessage,
  Message,
  ToolResultMessage,
  UserMessage,
} from "@earendil-works/pi-ai";
import type {
  AgentContent,
  AgentConversationEvent,
  AgentToolCallStatus,
} from "@posthog/shared";
import { type PiToolName, TOOL_KIND_BY_NAME } from "./toolKind";
import { bashTranslator } from "./tools/bashTranslator";
import { editTranslator } from "./tools/editTranslator";
import { findTranslator } from "./tools/findTranslator";
import { grepTranslator } from "./tools/grepTranslator";
import { lsTranslator } from "./tools/lsTranslator";
import { readTranslator } from "./tools/readTranslator";
import { writeTranslator } from "./tools/writeTranslator";
import type { PiToolTranslator } from "./toolTranslator";

const TRANSLATOR_BY_NAME: Record<PiToolName, PiToolTranslator> = {
  read: readTranslator,
  bash: bashTranslator,
  edit: editTranslator,
  write: writeTranslator,
  grep: grepTranslator,
  find: findTranslator,
  ls: lsTranslator,
};

interface PendingToolCall {
  name: string;
  arguments: unknown;
}

interface PiToolExecutionResult {
  content: ToolResultMessage["content"];
  details?: unknown;
}

function isPiToolName(name: string): name is PiToolName {
  return name in TOOL_KIND_BY_NAME;
}

function toContent(block: {
  type: string;
  text?: string;
  data?: string;
  mimeType?: string;
}): AgentContent | undefined {
  if (block.type === "text" && typeof block.text === "string") {
    return { type: "text", text: block.text };
  }

  if (
    block.type === "image" &&
    typeof block.data === "string" &&
    typeof block.mimeType === "string"
  ) {
    return { type: "image", data: block.data, mimeType: block.mimeType };
  }

  return undefined;
}

export interface PiMessageTranslator {
  translate(message: Message): AgentConversationEvent[];
  translateToolExecutionStart(
    toolCallId: string,
    toolName: string,
    args: unknown,
    timestamp: number,
  ): AgentConversationEvent[];
  translateToolExecutionUpdate(
    toolCallId: string,
    toolName: string,
    args: unknown,
    result: PiToolExecutionResult,
    timestamp: number,
  ): AgentConversationEvent[];
  translateToolExecutionEnd(
    toolCallId: string,
    toolName: string,
    result: PiToolExecutionResult,
    isError: boolean,
    timestamp: number,
  ): AgentConversationEvent[];
}

export function createPiMessageTranslator(): PiMessageTranslator {
  const pendingToolCalls = new Map<string, PendingToolCall>();
  let userMessageId = 0;

  function translateUser(message: UserMessage): AgentConversationEvent[] {
    const content =
      typeof message.content === "string"
        ? [{ type: "text" as const, text: message.content }]
        : message.content.flatMap((block) => {
            const translated = toContent(block);
            return translated ? [translated] : [];
          });

    if (content.length === 0) {
      return [];
    }

    userMessageId += 1;

    return [
      {
        type: "user_message",
        id: `pi-user-${message.timestamp}-${userMessageId}`,
        timestamp: message.timestamp,
        content,
      },
    ];
  }

  function translateAssistant(
    message: AssistantMessage,
  ): AgentConversationEvent[] {
    const events: AgentConversationEvent[] = [];

    for (const block of message.content) {
      if (block.type === "text") {
        events.push({
          type: "assistant_message_chunk",
          timestamp: message.timestamp,
          content: { type: "text", text: block.text },
        });
        continue;
      }

      if (block.type === "thinking") {
        events.push({
          type: "assistant_thought_chunk",
          timestamp: message.timestamp,
          content: { type: "text", text: block.thinking },
        });
        continue;
      }

      if (block.type === "toolCall") {
        pendingToolCalls.set(block.id, {
          name: block.name,
          arguments: block.arguments,
        });

        const kind = isPiToolName(block.name)
          ? TOOL_KIND_BY_NAME[block.name]
          : null;

        events.push({
          type: "tool_call_started",
          timestamp: message.timestamp,
          toolCall: {
            id: block.id,
            title: block.name,
            kind,
            status: "pending",
            rawInput: block.arguments,
          },
        });
      }
    }

    if (message.stopReason === "error") {
      events.push({
        type: "runtime_error",
        timestamp: message.timestamp,
        errorType: "pi_runtime",
        message: message.errorMessage ?? "Pi runtime failed",
      });
    }

    return events;
  }

  function translateToolExecution(
    toolCallId: string,
    toolName: string,
    args: unknown,
    result: PiToolExecutionResult,
    status: AgentToolCallStatus,
    timestamp: number,
  ): AgentConversationEvent[] {
    const toolCall: Extract<
      AgentConversationEvent,
      { type: "tool_call_updated" }
    >["toolCall"] = {
      id: toolCallId,
      status,
      rawOutput: result.content,
    };

    const translator = isPiToolName(toolName)
      ? TRANSLATOR_BY_NAME[toolName]
      : undefined;

    if (translator) {
      const output = translator({
        toolCallId,
        arguments: args,
        resultContent: result.content,
        details: result.details,
        isError: status === "failed",
      });

      if (output.content) {
        toolCall.content = output.content;
      }

      if (output.locations) {
        toolCall.locations = output.locations;
      }
    }

    return [{ type: "tool_call_updated", timestamp, toolCall }];
  }

  function translateToolResult(
    message: ToolResultMessage,
  ): AgentConversationEvent[] {
    const pending = pendingToolCalls.get(message.toolCallId);
    pendingToolCalls.delete(message.toolCallId);

    return translateToolExecution(
      message.toolCallId,
      message.toolName,
      pending?.arguments,
      { content: message.content, details: message.details },
      message.isError ? "failed" : "completed",
      message.timestamp,
    );
  }

  return {
    translate(message: Message): AgentConversationEvent[] {
      if (message.role === "user") {
        return translateUser(message);
      }

      if (message.role === "assistant") {
        return translateAssistant(message);
      }

      return translateToolResult(message);
    },

    translateToolExecutionStart(toolCallId, toolName, args, timestamp) {
      pendingToolCalls.set(toolCallId, { name: toolName, arguments: args });

      return [
        {
          type: "tool_call_updated",
          timestamp,
          toolCall: { id: toolCallId, status: "in_progress" },
        },
      ];
    },

    translateToolExecutionUpdate(
      toolCallId,
      toolName,
      args,
      result,
      timestamp,
    ) {
      return translateToolExecution(
        toolCallId,
        toolName,
        args,
        result,
        "in_progress",
        timestamp,
      );
    },

    translateToolExecutionEnd(
      toolCallId,
      toolName,
      result,
      isError,
      timestamp,
    ) {
      const pending = pendingToolCalls.get(toolCallId);

      return translateToolExecution(
        toolCallId,
        toolName,
        pending?.arguments,
        result,
        isError ? "failed" : "completed",
        timestamp,
      );
    },
  };
}
