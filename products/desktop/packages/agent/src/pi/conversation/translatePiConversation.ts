import type { AssistantMessage, Message } from "@earendil-works/pi-ai";
import type { JsonAgentSessionEvent } from "@earendil-works/pi-coding-agent";
import {
  AGENT_FLOW_MESSAGE_TYPE,
  AGENT_FLOW_STEP_EVENT_TYPE,
  type AgentConversationEvent,
  type AgentFlowMessageDetails,
  type AgentFlowMessageStatus,
  type AgentFlowStepStreamEvent,
  agentFlowApprovalCardId,
  agentFlowMessageDetailsSchema,
  agentFlowStepCardId,
  agentFlowStepStreamEventSchema,
  isAgentFlowTerminalStatus,
} from "@posthog/shared";
import { isPiToolName, TOOL_KIND_BY_NAME } from "./toolKind";
import { createPiMessageTranslator } from "./translatePiMessage";

type AgentMessage = Extract<
  JsonAgentSessionEvent,
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

function customMessageEvents(
  message: AgentMessage,
  flowSteps: FlowStepCards,
  flowStepCardText: FlowStepCardText,
  flowApprovals: FlowStepCards,
): AgentConversationEvent[] {
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

  const flowDetails = agentFlowDetails(message);
  if (flowDetails) {
    return agentFlowEvents(
      message.timestamp,
      text,
      flowDetails,
      flowSteps,
      flowStepCardText,
      flowApprovals,
    );
  }

  return [
    {
      type: "assistant_message_chunk",
      timestamp: message.timestamp,
      content: { type: "text", text },
    },
  ];
}

const AGENT_FLOW_STOP_REASONS: Partial<Record<AgentFlowMessageStatus, string>> =
  {
    completed: "stop",
    stopped: "aborted",
    failed: "error",
  };

type FlowStepCards = Map<string, string>;

type FlowStepCardText = Map<string, string>;

const STEP_CARD_TEXT_CAP = 4_000;

function flowStepStreamEvents(
  payload: AgentFlowStepStreamEvent,
  cardText: FlowStepCardText,
): AgentConversationEvent[] {
  const cardId = agentFlowStepCardId(payload.flowId, payload.stepIndex);
  const stepEvent = payload.event;

  if (stepEvent.kind === "tool_start") {
    return [
      {
        type: "tool_call_started",
        timestamp: payload.timestamp,
        toolCall: {
          id: `${cardId}:${stepEvent.toolCallId}`,
          parentId: cardId,
          title: stepEvent.title ?? stepEvent.toolName,
          kind: isPiToolName(stepEvent.toolName)
            ? TOOL_KIND_BY_NAME[stepEvent.toolName]
            : "other",
          status: "in_progress",
          ...(stepEvent.path ? { locations: [{ path: stepEvent.path }] } : {}),
          ...(stepEvent.diff
            ? {
                content: [
                  {
                    type: "diff",
                    path: stepEvent.diff.path,
                    oldText: stepEvent.diff.oldText ?? null,
                    newText: stepEvent.diff.newText,
                  },
                ],
              }
            : {}),
        },
      },
    ];
  }

  if (stepEvent.kind === "tool_end") {
    const keepsDiff =
      stepEvent.toolName === "edit" || stepEvent.toolName === "write";
    return [
      {
        type: "tool_call_updated",
        timestamp: payload.timestamp,
        toolCall: {
          id: `${cardId}:${stepEvent.toolCallId}`,
          status: stepEvent.isError ? "failed" : "completed",
          ...(stepEvent.outputPreview && !keepsDiff
            ? {
                content: [
                  {
                    type: "content",
                    content: { type: "text", text: stepEvent.outputPreview },
                  },
                ],
              }
            : {}),
        },
      },
    ];
  }

  const combined = [cardText.get(cardId), stepEvent.text]
    .filter(Boolean)
    .join("\n\n");
  const capped = combined.slice(-STEP_CARD_TEXT_CAP);
  cardText.set(cardId, capped);
  return [
    {
      type: "tool_call_updated",
      timestamp: payload.timestamp,
      toolCall: {
        id: cardId,
        content: [{ type: "content", content: { type: "text", text: capped } }],
      },
    },
  ];
}

function agentFlowDetails(
  message: AgentMessage,
): AgentFlowMessageDetails | undefined {
  if (
    message.role !== "custom" ||
    message.customType !== AGENT_FLOW_MESSAGE_TYPE
  ) {
    return undefined;
  }
  const details = agentFlowMessageDetailsSchema.safeParse(message.details);
  return details.success ? details.data : undefined;
}

function agentFlowEvents(
  timestamp: number,
  text: string,
  details: AgentFlowMessageDetails,
  flowSteps: FlowStepCards,
  flowStepCardText: FlowStepCardText,
  flowApprovals: FlowStepCards,
): AgentConversationEvent[] {
  const events: AgentConversationEvent[] = [];

  if (details.event === "approval_requested" && details.approvalId) {
    const cardId = agentFlowApprovalCardId(details.flowId, details.approvalId);
    flowApprovals.set(details.flowId, cardId);
    return [
      {
        type: "tool_call_started",
        timestamp,
        toolCall: {
          id: cardId,
          title: `Review the ${details.stepName ?? "step"} handoff`,
          kind: "question",
          status: "in_progress",
          content: [{ type: "content", content: { type: "text", text } }],
        },
      },
    ];
  }

  if (details.event === "approval_resolved" && details.approvalId) {
    flowApprovals.delete(details.flowId);
    return [
      {
        type: "tool_call_updated",
        timestamp,
        toolCall: {
          id: agentFlowApprovalCardId(details.flowId, details.approvalId),
          status:
            details.approvalOutcome === "approved" ? "completed" : "failed",
          content: [{ type: "content", content: { type: "text", text } }],
        },
      },
    ];
  }

  if (details.event === "step_revising" && details.stepIndex !== undefined) {
    const cardId = agentFlowStepCardId(details.flowId, details.stepIndex);
    flowSteps.set(details.flowId, cardId);
    return [
      {
        type: "tool_call_updated",
        timestamp,
        toolCall: { id: cardId, status: "in_progress" },
      },
    ];
  }

  if (details.event === "step_started" && details.stepIndex !== undefined) {
    const cardId = agentFlowStepCardId(details.flowId, details.stepIndex);
    flowSteps.set(details.flowId, cardId);
    const cardEvents: AgentConversationEvent[] = [
      {
        type: "tool_call_started",
        timestamp,
        toolCall: {
          id: cardId,
          title: text.replaceAll("**", "").trim(),
          kind: "other",
          status: "in_progress",
        },
      },
    ];
    if (details.stepPrompt) {
      cardEvents.push({
        type: "tool_call_started",
        timestamp,
        toolCall: {
          id: `${cardId}:prompt`,
          parentId: cardId,
          title: "Prompt",
          kind: "other",
          status: "completed",
          content: [
            {
              type: "content",
              content: { type: "text", text: details.stepPrompt },
            },
          ],
        },
      });
    }
    return cardEvents;
  }

  if (details.event === "step_finished" && details.stepIndex !== undefined) {
    flowSteps.delete(details.flowId);
    flowStepCardText.delete(
      agentFlowStepCardId(details.flowId, details.stepIndex),
    );
    return [
      {
        type: "tool_call_updated",
        timestamp,
        toolCall: {
          id: agentFlowStepCardId(details.flowId, details.stepIndex),
          status: "completed",
          content: [{ type: "content", content: { type: "text", text } }],
        },
      },
    ];
  }

  if (isAgentFlowTerminalStatus(details.status)) {
    for (const open of [flowSteps, flowApprovals]) {
      const openCardId = open.get(details.flowId);
      if (openCardId) {
        open.delete(details.flowId);
        events.push({
          type: "tool_call_updated",
          timestamp,
          toolCall: { id: openCardId, status: "failed" },
        });
      }
    }
  }

  events.push({
    type: "assistant_message_chunk",
    timestamp,
    content: { type: "text", text },
  });

  if (isAgentFlowTerminalStatus(details.status)) {
    events.push({
      type: "turn_completed",
      timestamp,
      stopReason: AGENT_FLOW_STOP_REASONS[details.status],
    });
  }

  return events;
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

interface ActiveAssistantStream {
  timestamp: number;
  textByContentIndex: Map<number, string>;
  thinkingByContentIndex: Map<number, string>;
}

export interface PiConversationTranslator {
  beginDirectBash(command: string): AgentConversationEvent[];
  completeDirectBash(result: PiDirectBashResult): AgentConversationEvent[];
  failDirectBash(message: string): AgentConversationEvent[];
  translateHistoryMessage(message: AgentMessage): AgentConversationEvent[];
  translateEvent(event: JsonAgentSessionEvent): AgentConversationEvent[];
}

export function createPiConversationTranslator(): PiConversationTranslator {
  const messageTranslator = createPiMessageTranslator();
  const flowSteps: FlowStepCards = new Map();
  const flowStepCardText: FlowStepCardText = new Map();
  const flowApprovals: FlowStepCards = new Map();
  let historyTurnActive = false;
  let activeAssistantStream: ActiveAssistantStream | undefined;
  let latestRuntimeTimestamp = 0;
  let latestConversationTimestamp = 0;
  let turnTotalTokens = 0;
  let pendingRuntimeError: AgentConversationEvent | undefined;
  let settledStopReason: string | undefined;
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
      events.push(
        ...customMessageEvents(
          message,
          flowSteps,
          flowStepCardText,
          flowApprovals,
        ),
      );
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

  function reconcileAssistantContent(
    message: AssistantMessage,
    events: AgentConversationEvent[],
    stream: ActiveAssistantStream,
  ): AgentConversationEvent[] {
    const textContentIndexes = message.content.flatMap((content, index) =>
      content.type === "text" ? [index] : [],
    );
    const thinkingContentIndexes = message.content.flatMap((content, index) =>
      content.type === "thinking" ? [index] : [],
    );
    const reconciled: AgentConversationEvent[] = [];
    let textIndex = 0;
    let thinkingIndex = 0;

    for (const translated of events) {
      let contentIndex: number | undefined;
      let streamed = "";

      if (translated.type === "assistant_message_chunk") {
        contentIndex = textContentIndexes[textIndex++];
        streamed = stream.textByContentIndex.get(contentIndex ?? -1) ?? "";
      } else if (translated.type === "assistant_thought_chunk") {
        contentIndex = thinkingContentIndexes[thinkingIndex++];
        streamed = stream.thinkingByContentIndex.get(contentIndex ?? -1) ?? "";
      } else {
        reconciled.push(translated);
        continue;
      }

      if (translated.content.type !== "text" || !streamed) {
        reconciled.push(translated);
        continue;
      }

      const finalText = translated.content.text;
      if (finalText === streamed) {
        continue;
      }
      if (!finalText.startsWith(streamed)) {
        continue;
      }

      reconciled.push({
        ...translated,
        content: { type: "text", text: finalText.slice(streamed.length) },
      });
    }

    return reconciled;
  }

  function translateEvent(
    event: JsonAgentSessionEvent,
  ): AgentConversationEvent[] {
    if ((event as { type: string }).type === AGENT_FLOW_STEP_EVENT_TYPE) {
      const parsed = agentFlowStepStreamEventSchema.safeParse(event);
      return parsed.success
        ? flowStepStreamEvents(parsed.data, flowStepCardText)
        : [];
    }

    if (event.type === "message_start") {
      activeAssistantStream = undefined;
      if (event.message.role !== "assistant") {
        return [];
      }

      activeAssistantStream = {
        timestamp: event.message.timestamp,
        textByContentIndex: new Map(),
        thinkingByContentIndex: new Map(),
      };
      latestRuntimeTimestamp = Math.max(
        latestRuntimeTimestamp,
        activeAssistantStream.timestamp,
      );
      latestConversationTimestamp = Math.max(
        latestConversationTimestamp,
        activeAssistantStream.timestamp,
      );
      return [];
    }

    if (event.type === "message_update") {
      const stream = activeAssistantStream;
      if (!stream) {
        return [];
      }

      const update = event.assistantMessageEvent;
      if (update.type === "text_delta" && update.delta) {
        const streamedText = stream.textByContentIndex.get(update.contentIndex);
        stream.textByContentIndex.set(
          update.contentIndex,
          `${streamedText ?? ""}${update.delta}`,
        );
        return [
          ...completeRetry(stream.timestamp),
          {
            type: "assistant_message_chunk",
            timestamp: stream.timestamp,
            content: { type: "text", text: update.delta },
          },
        ];
      }

      if (update.type === "thinking_delta" && update.delta) {
        const streamedThinking = stream.thinkingByContentIndex.get(
          update.contentIndex,
        );
        stream.thinkingByContentIndex.set(
          update.contentIndex,
          `${streamedThinking ?? ""}${update.delta}`,
        );
        return [
          ...completeRetry(stream.timestamp),
          {
            type: "assistant_thought_chunk",
            timestamp: stream.timestamp,
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
      const assistantStream =
        event.message.role === "assistant" &&
        activeAssistantStream?.timestamp === event.message.timestamp
          ? activeAssistantStream
          : undefined;
      activeAssistantStream = undefined;

      latestRuntimeTimestamp = Math.max(
        latestRuntimeTimestamp,
        event.message.timestamp,
      );
      latestConversationTimestamp = Math.max(
        latestConversationTimestamp,
        event.message.timestamp,
      );

      if (!isMessage(event.message)) {
        return customMessageEvents(
          event.message,
          flowSteps,
          flowStepCardText,
          flowApprovals,
        );
      }

      if (isAssistantMessage(event.message)) {
        settledStopReason = event.message.stopReason;
      }

      const events = messageTranslator.translate(event.message);
      const runtimeError = events.find(
        (translated) => translated.type === "runtime_error",
      );
      if (runtimeError) {
        pendingRuntimeError = runtimeError;
      }

      let visibleEvents: AgentConversationEvent[] = events.filter(
        (translated) => translated.type !== "runtime_error",
      );
      if (event.message.role !== "assistant") {
        return visibleEvents;
      }

      if (assistantStream) {
        visibleEvents = reconcileAssistantContent(
          event.message,
          visibleEvents,
          assistantStream,
        );
      }

      turnTotalTokens += event.message.usage.totalTokens;

      return visibleEvents;
    }

    if (event.type === "agent_end") {
      activeAssistantStream = undefined;
      const runtimeError = pendingRuntimeError;
      pendingRuntimeError = undefined;

      if (!event.willRetry) {
        turnTotalTokens = 0;
      }

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
      activeAssistantStream = undefined;

      const timestamp = Math.max(Date.now(), latestRuntimeTimestamp);
      const hadRuntimeActivity = latestRuntimeTimestamp > 0;
      const stopReason = settledStopReason;
      latestRuntimeTimestamp = 0;
      settledStopReason = undefined;
      const totalTokens = turnTotalTokens;
      turnTotalTokens = 0;

      return hadRuntimeActivity
        ? [
            {
              type: "turn_completed",
              timestamp,
              stopReason,
              ...(totalTokens > 0 ? { totalTokens } : {}),
            },
          ]
        : [];
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
