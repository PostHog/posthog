import {
  type AcpMessage,
  isJsonRpcNotification,
  readMcpToolDescriptor,
} from "@posthog/shared";

export type ToolCallUpdate = {
  toolCallId: string;
  tool: string | undefined;
  status: string | undefined;
  rawInput: unknown;
};

export function readToolCallUpdate(event: AcpMessage): ToolCallUpdate | null {
  const msg = event.message;
  if (!isJsonRpcNotification(msg) || msg.method !== "session/update") {
    return null;
  }
  const update = (
    msg.params as
      | {
          update?: {
            sessionUpdate?: string;
            toolCallId?: string;
            status?: string;
            rawInput?: unknown;
            _meta?: unknown;
          };
        }
      | undefined
  )?.update;
  if (
    !update?.toolCallId ||
    (update.sessionUpdate !== "tool_call" &&
      update.sessionUpdate !== "tool_call_update")
  ) {
    return null;
  }
  return {
    toolCallId: update.toolCallId,
    tool: readMcpToolDescriptor(update._meta)?.tool,
    status: update.status,
    rawInput: update.rawInput,
  };
}
