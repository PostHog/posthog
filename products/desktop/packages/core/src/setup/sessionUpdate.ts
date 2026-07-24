import type { ActivityEntry } from "@posthog/core/setup/setupState";

let activityIdCounter = 0;

export function nextActivityId(): number {
  activityIdCounter += 1;
  return activityIdCounter;
}

export function extractPathFromRawInput(
  tool: string,
  rawInput: Record<string, unknown> | undefined,
): string | null {
  if (!rawInput) return null;

  switch (tool) {
    case "Read":
    case "Edit":
    case "Write":
      return (rawInput.file_path as string) ?? null;
    case "Grep":
      return (rawInput.pattern as string)
        ? `"${rawInput.pattern}"${rawInput.path ? ` in ${rawInput.path}` : ""}`
        : ((rawInput.path as string) ?? null);
    case "Glob":
      return (rawInput.pattern as string) ?? null;
    case "Bash": {
      const cmd = rawInput.command as string | undefined;
      if (!cmd) return null;
      return cmd.length > 80 ? `${cmd.slice(0, 77)}...` : cmd;
    }
    default: {
      const filePath =
        rawInput.file_path ?? rawInput.path ?? rawInput.notebook_path;
      if (typeof filePath === "string") return filePath;
      const pattern = rawInput.pattern;
      if (typeof pattern === "string") return `"${pattern}"`;
      const command = rawInput.command;
      if (typeof command === "string")
        return command.length > 80 ? `${command.slice(0, 77)}...` : command;
      const url = rawInput.url;
      if (typeof url === "string") return url;
      const query = rawInput.query;
      if (typeof query === "string") return query;
      return null;
    }
  }
}

export function extractToolCall(
  update: Record<string, unknown>,
): ActivityEntry | null {
  const sessionUpdate = update.sessionUpdate as string | undefined;
  if (sessionUpdate !== "tool_call" && sessionUpdate !== "tool_call_update")
    return null;

  const meta = update._meta as
    | { claudeCode?: { toolName?: string } }
    | undefined;
  const tool = meta?.claudeCode?.toolName ?? "Working";
  const locations = update.locations as
    | { path?: string; line?: number }[]
    | undefined;
  const rawInput = (update.rawInput ?? update.input) as
    | Record<string, unknown>
    | undefined;
  const filePath =
    locations?.[0]?.path ?? extractPathFromRawInput(tool, rawInput);
  const title = (update.title as string) ?? "";
  const toolCallId = (update.toolCallId as string) ?? "";

  return { id: nextActivityId(), toolCallId, tool, filePath, title };
}

export function extractAgentMessageText(
  update: Record<string, unknown>,
): string | null {
  if (update.sessionUpdate !== "agent_message_chunk") return null;
  const content = update.content as
    | { type?: string; text?: string }
    | undefined;
  if (content?.type !== "text" || !content.text) return null;
  return content.text;
}

export function handleSessionUpdate(
  payload: unknown,
  pushActivity: (entry: ActivityEntry) => void,
  pushAssistantText?: (text: string) => void,
): void {
  const acpMsg = payload as { message?: Record<string, unknown> };
  const inner = acpMsg.message;
  if (!inner) return;

  if ("method" in inner && inner.method === "session/update") {
    const params = inner.params as Record<string, unknown> | undefined;
    if (!params) return;

    const update = (params.update as Record<string, unknown>) ?? params;

    const entry = extractToolCall(update);
    if (entry) {
      pushActivity(entry);
      return;
    }

    if (pushAssistantText) {
      const text = extractAgentMessageText(update);
      if (text) pushAssistantText(text);
    }
  }
}
