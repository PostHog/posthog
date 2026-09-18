import { describe, expect, it } from "vitest";
import { type ConversationTurn, formatConversationForResume } from "./resume";

describe("formatConversationForResume", () => {
  const userTurn = (text: string): ConversationTurn => ({
    role: "user",
    content: [{ type: "text", text }],
  });

  it("keeps earlier turns when a stored tool result dwarfs the summary it renders", () => {
    const conversation: ConversationTurn[] = [
      userTurn("read the config"),
      {
        role: "assistant",
        content: [{ type: "text", text: "reading it now" }],
        toolCalls: [
          {
            toolCallId: "call-1",
            toolName: "Read",
            input: { file_path: "/config.ts" },
            result: "x".repeat(200_000),
          },
        ],
      },
      userTurn("now fix it"),
      {
        role: "assistant",
        content: [{ type: "text", text: "on it" }],
      },
    ];

    const summary = formatConversationForResume(conversation);

    expect(summary).not.toContain("earlier turns omitted");
    expect(summary).toContain("read the config");
    expect(summary).toContain(`  - Read → ${"x".repeat(2000)}...(truncated)`);
  });

  it("cuts a shell call named after its whole command to a first-line preview", () => {
    const command = `cat > /tmp/out <<'EOF'\n${"payload line\n".repeat(5_000)}EOF`;

    const summary = formatConversationForResume([
      userTurn("write the file"),
      {
        role: "assistant",
        content: [],
        toolCalls: [
          {
            toolCallId: "call-1",
            toolName: command,
            input: {},
            result: "done",
          },
        ],
      },
    ]);

    expect(summary).toContain(
      "  - cat > /tmp/out <<'EOF'...(truncated) → done",
    );
    expect(summary).not.toContain("payload line");
  });

  it.each([
    {
      name: "a result under the cap in full",
      result: "3 files changed",
      expected: "  - Bash → 3 files changed",
    },
    {
      name: "a structured result as JSON",
      result: { content: [{ type: "text", text: "skill body" }] },
      expected: `  - Bash → {"content":[{"type":"text","text":"skill body"}]}`,
    },
  ])("renders $name", ({ result, expected }) => {
    const summary = formatConversationForResume([
      userTurn("run it"),
      {
        role: "assistant",
        content: [],
        toolCalls: [
          { toolCallId: "call-1", toolName: "Bash", input: {}, result },
        ],
      },
    ]);

    expect(summary).toContain(expected);
  });
});
