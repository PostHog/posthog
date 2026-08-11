import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { extractSearchableText } from "@posthog/ui/features/sessions/utils/extractSearchableText";
import { describe, expect, it } from "vitest";

describe("extractSearchableText", () => {
  it("extracts user message content", () => {
    const item: ConversationItem = {
      type: "user_message",
      id: "1",
      content: "hello world",
      timestamp: 0,
    };
    expect(extractSearchableText(item)).toBe("hello world");
  });

  it("extracts agent message text chunk", () => {
    const item: ConversationItem = {
      type: "session_update",
      id: "2",
      update: {
        sessionUpdate: "agent_message_chunk",
        content: { type: "text", text: "agent reply" },
      },
      turnContext: {
        toolCalls: new Map(),
        childItems: new Map(),
        turnCancelled: false,
        turnComplete: true,
      },
    };
    expect(extractSearchableText(item)).toBe("agent reply");
  });

  it("extracts agent thought text chunk", () => {
    const item: ConversationItem = {
      type: "session_update",
      id: "3",
      update: {
        sessionUpdate: "agent_thought_chunk",
        content: { type: "text", text: "thinking..." },
      },
      turnContext: {
        toolCalls: new Map(),
        childItems: new Map(),
        turnCancelled: false,
        turnComplete: true,
      },
    };
    expect(extractSearchableText(item)).toBe("thinking...");
  });

  it("returns empty string for non-text agent chunks", () => {
    const item: ConversationItem = {
      type: "session_update",
      id: "4",
      update: {
        sessionUpdate: "agent_message_chunk",
        content: {
          type: "image",
          data: "base64data",
          mimeType: "image/png",
        },
      },
      turnContext: {
        toolCalls: new Map(),
        childItems: new Map(),
        turnCancelled: false,
        turnComplete: true,
      },
    };
    expect(extractSearchableText(item)).toBe("");
  });

  it("returns empty string for tool calls", () => {
    const item: ConversationItem = {
      type: "session_update",
      id: "5",
      update: {
        sessionUpdate: "tool_call",
        toolCallId: "tc-1",
        title: "Read file",
      },
      turnContext: {
        toolCalls: new Map(),
        childItems: new Map(),
        turnCancelled: false,
        turnComplete: true,
      },
    };
    expect(extractSearchableText(item)).toBe("");
  });

  it("extracts console message", () => {
    const item: ConversationItem = {
      type: "session_update",
      id: "6",
      update: {
        sessionUpdate: "console",
        level: "info",
        message: "console output",
      },
      turnContext: {
        toolCalls: new Map(),
        childItems: new Map(),
        turnCancelled: false,
        turnComplete: true,
      },
    };
    expect(extractSearchableText(item)).toBe("console output");
  });

  it("extracts error message", () => {
    const item: ConversationItem = {
      type: "session_update",
      id: "7",
      update: {
        sessionUpdate: "error",
        errorType: "FatalError",
        message: "something broke",
      },
      turnContext: {
        toolCalls: new Map(),
        childItems: new Map(),
        turnCancelled: false,
        turnComplete: true,
      },
    };
    expect(extractSearchableText(item)).toBe("something broke");
  });

  it("extracts status text", () => {
    const item: ConversationItem = {
      type: "session_update",
      id: "8",
      update: {
        sessionUpdate: "status",
        status: "running",
      },
      turnContext: {
        toolCalls: new Map(),
        childItems: new Map(),
        turnCancelled: false,
        turnComplete: true,
      },
    };
    expect(extractSearchableText(item)).toBe("running");
  });

  it("extracts task notification summary", () => {
    const item: ConversationItem = {
      type: "session_update",
      id: "9",
      update: {
        sessionUpdate: "task_notification",
        taskId: "t1",
        status: "completed",
        summary: "task done",
        outputFile: "/tmp/out",
      },
      turnContext: {
        toolCalls: new Map(),
        childItems: new Map(),
        turnCancelled: false,
        turnComplete: true,
      },
    };
    expect(extractSearchableText(item)).toBe("task done");
  });

  it("joins shell command with stdout and stderr", () => {
    const item: ConversationItem = {
      type: "user_shell_execute",
      id: "10",
      command: "ls -la",
      cwd: "/tmp",
      result: { stdout: "file.txt", stderr: "warning", exitCode: 0 },
    };
    expect(extractSearchableText(item)).toBe("ls -la file.txt warning");
  });

  it("returns just the command when shell execute has no result", () => {
    const item: ConversationItem = {
      type: "user_shell_execute",
      id: "11",
      command: "echo hi",
      cwd: "/tmp",
    };
    expect(extractSearchableText(item)).toBe("echo hi  ");
  });

  it("falls back to default text for turn_cancelled without reason", () => {
    const item: ConversationItem = {
      type: "turn_cancelled",
      id: "12",
    };
    expect(extractSearchableText(item)).toBe("Interrupted by user");
  });

  it("uses provided interruptReason on turn_cancelled", () => {
    const item: ConversationItem = {
      type: "turn_cancelled",
      id: "13",
      interruptReason: "moving_to_worktree",
    };
    expect(extractSearchableText(item)).toBe("moving_to_worktree");
  });

  it.each(["git_action", "skill_button_action", "git_action_result"] as const)(
    "returns empty string for %s items",
    (type) => {
      const item = {
        type,
        id: "x",
        actionType: "commit",
        buttonId: "btn",
        turnId: "t",
      } as unknown as ConversationItem;
      expect(extractSearchableText(item)).toBe("");
    },
  );
});
