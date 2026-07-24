import type { AssistantMessage, Message } from "@earendil-works/pi-ai";
import type { AgentSessionEvent } from "@earendil-works/pi-coding-agent";
import type { AgentConversationEvent } from "@posthog/shared";
import { createPiMessageTranslator } from "./translatePiMessage";

type AgentMessage = Extract<
  AgentSessionEvent,
  { type: "message_end" }
>["message"];

function isMessage(message: AgentMessage): message is Message {
  return (
    message.role === "user" ||
    message.role === "assistant" ||
    message.role === "toolResult"
  );
}

function customMessageEvents(message: AgentMessage): AgentConversationEvent[] {
  if (message.role === "bashExecution") {
    const id = `pi-bash-${message.timestamp}`;
    const failed = message.cancelled || (message.exitCode ?? 0) !== 0;

    return [
      {
        type: "tool_call_started",
        timestamp: message.timestamp,
        toolCall: {
          id,
          title: message.command,
          kind: "execute",
          status: "in_progress",
          rawInput: { command: message.command },
        },
      },
      {
        type: "tool_call_updated",
        timestamp: message.timestamp,
        toolCall: {
          id,
          status: failed ? "failed" : "completed",
          rawOutput: message.output,
          content: message.output
            ? [
                {
                  type: "content",
                  content: { type: "text", text: message.output },
                },
              ]
            : [],
        },
      },
    ];
  }

  let text: string | undefined;

  if (
    message.role === "branchSummary" ||
    message.role === "compactionSummary"
  ) {
    text = message.summary;
  } else if (message.role === "custom" && message.display) {
    text =
      typeof message.content === "string"
        ? message.content
        : message.content
            .flatMap((content) =>
              content.type === "text" ? [content.text] : [],
            )
            .join("\n");
  }

  if (!text) {
    return [];
  }

  return [
    {
      type: "assistant_message_chunk",
      timestamp: message.timestamp,
      content: { type: "text", text },
    },
  ];
}

function isAssistantMessage(
  message: AgentMessage,
): message is AssistantMessage {
  return message.role === "assistant";
}

export interface PiConversationTranslator {
  translateHistoryMessage(message: AgentMessage): AgentConversationEvent[];
  translateEvent(event: AgentSessionEvent): AgentConversationEvent[];
}

export function createPiConversationTranslator(): PiConversationTranslator {
  const messageTranslator = createPiMessageTranslator();
  const streamedAssistantTimestamps = new Set<number>();
  let historyTurnActive = false;
  let latestRuntimeTimestamp = 0;
  let latestConversationTimestamp = 0;
  let pendingRuntimeError: AgentConversationEvent | undefined;

  function translateHistoryMessage(
    message: AgentMessage,
  ): AgentConversationEvent[] {
    const events: AgentConversationEvent[] = [];
    latestConversationTimestamp = Math.max(
      latestConversationTimestamp,
      message.timestamp,
    );

    if (message.role === "user" && historyTurnActive) {
      events.push({
        type: "turn_completed",
        timestamp: message.timestamp,
      });
      historyTurnActive = false;
    }

    if (isMessage(message)) {
      events.push(...messageTranslator.translate(message));
    } else {
      events.push(...customMessageEvents(message));
    }

    if (message.role === "user") {
      historyTurnActive = true;
    }

    if (
      isAssistantMessage(message) &&
      message.stopReason !== "toolUse" &&
      historyTurnActive
    ) {
      events.push({
        type: "turn_completed",
        timestamp: message.timestamp,
        stopReason: message.stopReason,
      });
      historyTurnActive = false;
    }

    return events;
  }

  function translateEvent(event: AgentSessionEvent): AgentConversationEvent[] {
    if (event.type === "message_update") {
      const update = event.assistantMessageEvent;
      latestRuntimeTimestamp = Math.max(
        latestRuntimeTimestamp,
        event.message.timestamp,
      );
      latestConversationTimestamp = Math.max(
        latestConversationTimestamp,
        event.message.timestamp,
      );

      if (update.type === "text_delta" && update.delta) {
        streamedAssistantTimestamps.add(event.message.timestamp);
        return [
          {
            type: "assistant_message_chunk",
            timestamp: event.message.timestamp,
            content: { type: "text", text: update.delta },
          },
        ];
      }

      if (update.type === "thinking_delta" && update.delta) {
        streamedAssistantTimestamps.add(event.message.timestamp);
        return [
          {
            type: "assistant_thought_chunk",
            timestamp: event.message.timestamp,
            content: { type: "text", text: update.delta },
          },
        ];
      }

      return [];
    }

    if (event.type === "tool_execution_start") {
      return messageTranslator.translateToolExecutionStart(
        event.toolCallId,
        event.toolName,
        event.args,
        latestRuntimeTimestamp,
      );
    }

    if (event.type === "tool_execution_update") {
      return messageTranslator.translateToolExecutionUpdate(
        event.toolCallId,
        event.toolName,
        event.args,
        event.partialResult,
        latestRuntimeTimestamp,
      );
    }

    if (event.type === "tool_execution_end") {
      return messageTranslator.translateToolExecutionEnd(
        event.toolCallId,
        event.toolName,
        event.result,
        event.isError,
        latestRuntimeTimestamp,
      );
    }

    if (event.type === "message_end") {
      latestRuntimeTimestamp = Math.max(
        latestRuntimeTimestamp,
        event.message.timestamp,
      );
      latestConversationTimestamp = Math.max(
        latestConversationTimestamp,
        event.message.timestamp,
      );

      if (!isMessage(event.message)) {
        return customMessageEvents(event.message);
      }

      const events = messageTranslator.translate(event.message);
      const runtimeError = events.find(
        (translated) => translated.type === "runtime_error",
      );
      if (runtimeError) {
        pendingRuntimeError = runtimeError;
      }

      const visibleEvents = events.filter(
        (translated) => translated.type !== "runtime_error",
      );
      if (
        event.message.role !== "assistant" ||
        !streamedAssistantTimestamps.has(event.message.timestamp)
      ) {
        return visibleEvents;
      }

      return visibleEvents.filter(
        (translated) =>
          translated.type !== "assistant_message_chunk" &&
          translated.type !== "assistant_thought_chunk",
      );
    }

    if (event.type === "agent_end") {
      const runtimeError = pendingRuntimeError;
      pendingRuntimeError = undefined;

      if (!event.willRetry && runtimeError) {
        return [runtimeError];
      }

      return [];
    }

    if (event.type === "auto_retry_start") {
      return [
        {
          type: "runtime_status",
          timestamp: latestConversationTimestamp,
          status: "retrying",
          message: event.errorMessage,
          attempt: event.attempt,
          maxAttempts: event.maxAttempts,
          delayMs: event.delayMs,
        },
      ];
    }

    if (event.type === "auto_retry_end") {
      const events: AgentConversationEvent[] = [
        {
          type: "runtime_status",
          timestamp: latestConversationTimestamp,
          status: "retrying",
          isComplete: true,
        },
      ];

      if (!event.success && event.finalError) {
        events.push({
          type: "runtime_error",
          timestamp: latestConversationTimestamp,
          errorType: "pi_runtime",
          message: event.finalError,
        });
      }

      return events;
    }

    if (event.type === "compaction_start") {
      return [
        {
          type: "runtime_status",
          timestamp: latestConversationTimestamp,
          status: "compacting",
        },
      ];
    }

    if (event.type === "compaction_end") {
      if (event.aborted || event.errorMessage) {
        return [
          {
            type: "runtime_status",
            timestamp: latestConversationTimestamp,
            status: "compacting_failed",
            error:
              event.errorMessage ??
              (event.aborted ? "Compaction cancelled" : undefined),
          },
        ];
      }

      return [
        {
          type: "runtime_status",
          timestamp: latestConversationTimestamp,
          status: "compacting",
          isComplete: true,
        },
      ];
    }

    if (event.type === "agent_settled") {
      streamedAssistantTimestamps.clear();

      const timestamp = latestRuntimeTimestamp;
      latestRuntimeTimestamp = 0;

      return timestamp > 0 ? [{ type: "turn_completed", timestamp }] : [];
    }

    return [];
  }

  return { translateHistoryMessage, translateEvent };
}
