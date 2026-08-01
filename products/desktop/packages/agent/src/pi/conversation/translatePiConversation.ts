import type { AssistantMessage, Message } from "@earendil-works/pi-ai";
import type { AgentSessionEvent } from "@earendil-works/pi-coding-agent";
import type { AgentConversationEvent } from "@posthog/shared";
import { createPiMessageTranslator } from "./translatePiMessage";

type AgentMessage = Extract<
  AgentSessionEvent,
  { type: "message_end" }
>["message"];

const utf8Encoder = new TextEncoder();

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
          origin: "user_shell",
        },
      },
      {
        type: "tool_call_updated",
        timestamp: message.timestamp,
        toolCall: {
          id,
          status: failed ? "failed" : "completed",
          rawOutput: message.output,
          origin: "user_shell",
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

export interface PiDirectBashResult {
  cancelled: boolean;
  exitCode: number | null;
  output: string;
}

export interface PiConversationTranslator {
  beginDirectBash(command: string): AgentConversationEvent[];
  completeDirectBash(result: PiDirectBashResult): AgentConversationEvent[];
  failDirectBash(message: string): AgentConversationEvent[];
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
  let retrying = false;
  let directBashSequence = 0;

  function completeRetry(timestamp: number): AgentConversationEvent[] {
    if (!retrying) {
      return [];
    }

    retrying = false;
    return [
      {
        type: "runtime_status",
        timestamp,
        status: "retrying",
        isComplete: true,
      },
    ];
  }

  let activeDirectBash:
    | {
        nextOutputBytes: number;
        output: string;
        outputBytes: number;
        startedAt: number;
        toolCallId: string;
      }
    | undefined;

  function beginDirectBash(command: string): AgentConversationEvent[] {
    const startedAt = Date.now();
    const toolCallId = `pi-bash-live-${startedAt}-${++directBashSequence}`;
    activeDirectBash = {
      nextOutputBytes: 4_096,
      output: "",
      outputBytes: 0,
      startedAt,
      toolCallId,
    };

    return [
      {
        type: "tool_call_started",
        timestamp: startedAt,
        toolCall: {
          id: toolCallId,
          title: command,
          kind: "execute",
          status: "in_progress",
          rawInput: { command },
          origin: "user_shell",
        },
      },
    ];
  }

  function finishDirectBash(
    status: "completed" | "failed",
    output: string,
  ): AgentConversationEvent[] {
    const directBash = activeDirectBash;
    activeDirectBash = undefined;
    if (!directBash) {
      return [];
    }

    return [
      {
        type: "tool_call_updated",
        timestamp: Date.now(),
        toolCall: {
          id: directBash.toolCallId,
          status,
          rawOutput: output,
          origin: "user_shell",
          content: output
            ? [
                {
                  type: "content",
                  content: { type: "text", text: output },
                },
              ]
            : [],
        },
      },
    ];
  }

  function completeDirectBash(
    result: PiDirectBashResult,
  ): AgentConversationEvent[] {
    const failed = result.cancelled || (result.exitCode ?? 0) !== 0;
    return finishDirectBash(failed ? "failed" : "completed", result.output);
  }

  function failDirectBash(message: string): AgentConversationEvent[] {
    const output = [activeDirectBash?.output, message]
      .filter(Boolean)
      .join("\n\n");
    return finishDirectBash("failed", output);
  }

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
          ...completeRetry(event.message.timestamp),
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
          ...completeRetry(event.message.timestamp),
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

    if (event.type === "bash_execution_update") {
      const directBash = activeDirectBash;
      if (!directBash) {
        return [];
      }

      directBash.output += event.delta;
      directBash.outputBytes += utf8Encoder.encode(event.delta).byteLength;
      if (directBash.outputBytes >= 4_096) {
        if (directBash.outputBytes < directBash.nextOutputBytes) {
          return [];
        }
        while (directBash.nextOutputBytes <= directBash.outputBytes) {
          directBash.nextOutputBytes *= 2;
        }
      }

      return [
        {
          type: "tool_call_updated",
          timestamp: directBash.startedAt,
          toolCall: {
            id: directBash.toolCallId,
            origin: "user_shell",
            content: directBash.output
              ? [
                  {
                    type: "content",
                    content: { type: "text", text: directBash.output },
                  },
                ]
              : [],
          },
        },
      ];
    }

    if (event.type === "queue_update") {
      return [
        {
          type: "queue_update",
          timestamp: Date.now(),
          steering: [...event.steering],
          followUp: [...event.followUp],
        },
      ];
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
      const completedEvents = completeRetry(latestConversationTimestamp);
      retrying = true;

      return [
        ...completedEvents,
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
      const events: AgentConversationEvent[] = completeRetry(
        latestConversationTimestamp,
      );

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

      const timestamp = event.result?.summary
        ? Math.max(Date.now(), latestConversationTimestamp + 1)
        : latestConversationTimestamp;
      latestConversationTimestamp = Math.max(
        latestConversationTimestamp,
        timestamp,
      );
      const events: AgentConversationEvent[] = [
        {
          type: "runtime_status",
          timestamp,
          status: "compacting",
          isComplete: true,
        },
      ];
      if (event.result?.summary) {
        events.push({
          type: "assistant_message_chunk",
          timestamp,
          content: { type: "text", text: event.result.summary },
        });
      }

      return events;
    }

    if (event.type === "agent_settled") {
      streamedAssistantTimestamps.clear();

      const timestamp = Math.max(Date.now(), latestRuntimeTimestamp);
      const hadRuntimeActivity = latestRuntimeTimestamp > 0;
      latestRuntimeTimestamp = 0;

      return hadRuntimeActivity ? [{ type: "turn_completed", timestamp }] : [];
    }

    return [];
  }

  return {
    beginDirectBash,
    completeDirectBash,
    failDirectBash,
    translateHistoryMessage,
    translateEvent,
  };
}
