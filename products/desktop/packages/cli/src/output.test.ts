import type { SessionNotification } from "@agentclientprotocol/sdk";
import { describe, expect, it } from "vitest";
import { createOutputSink } from "./output";

function makeFakeStdout() {
  const chunks: string[] = [];
  return {
    chunks,
    write(s: string): boolean {
      chunks.push(s);
      return true;
    },
    get output(): string {
      return chunks.join("");
    },
  };
}

function textUpdate(sessionId: string, text: string): SessionNotification {
  return {
    sessionId,
    update: {
      sessionUpdate: "agent_message_chunk",
      content: { type: "text", text },
    },
  };
}

// Some entries are deliberately partial protocol shapes (the sink must ignore
// them at runtime), so they are cast rather than fully constructed.
function ignoredUpdates(
  sessionId: string,
): { label: string; update: SessionNotification }[] {
  return [
    {
      label: "agent_thought_chunk",
      update: {
        sessionId,
        update: {
          sessionUpdate: "agent_thought_chunk",
          content: { type: "text", text: "thinking…" },
        },
      },
    },
    {
      label: "tool_call",
      update: {
        sessionId,
        update: { sessionUpdate: "tool_call", toolCallId: "tc1" },
      } as SessionNotification,
    },
    {
      label: "tool_call_update",
      update: {
        sessionId,
        update: { sessionUpdate: "tool_call_update", toolCallId: "tc1" },
      },
    },
    {
      label: "plan",
      update: {
        sessionId,
        update: { sessionUpdate: "plan", entries: [] },
      },
    },
    {
      label: "non-text content on agent_message_chunk",
      update: {
        sessionId,
        update: {
          sessionUpdate: "agent_message_chunk",
          content: { type: "image", data: "base64...", mimeType: "image/png" },
        },
      },
    },
  ];
}

describe("createOutputSink", () => {
  describe("text mode", () => {
    it("streams agent_message_chunk text to stdout immediately, in order", () => {
      const stdout = makeFakeStdout();
      const sink = createOutputSink("text", stdout);

      sink.onSessionUpdate(textUpdate("s1", "Hello, "));
      sink.onSessionUpdate(textUpdate("s1", "world"));
      sink.onSessionUpdate(textUpdate("s1", "!"));

      expect(stdout.output).toBe("Hello, world!");
    });

    it.each(ignoredUpdates("s1"))("ignores $label updates", ({ update }) => {
      const stdout = makeFakeStdout();
      const sink = createOutputSink("text", stdout);

      sink.onSessionUpdate(textUpdate("s1", "kept"));
      sink.onSessionUpdate(update);
      sink.onSessionUpdate(textUpdate("s1", " text"));

      expect(stdout.output).toBe("kept text");
    });

    it("emits the streamed text and a terminating newline, and nothing else", () => {
      const stdout = makeFakeStdout();
      const sink = createOutputSink("text", stdout);

      sink.onSessionUpdate(textUpdate("s1", "some streamed text"));
      sink.finish({ stopReason: "end_turn", sessionId: "s1" });

      // Exact equality, so text mode can't regress into appending a
      // finish-result JSON document after the streamed text.
      expect(stdout.output).toBe("some streamed text\n");
    });

    it("writes nothing at all when the turn produced no assistant text", () => {
      const stdout = makeFakeStdout();
      const sink = createOutputSink("text", stdout);

      sink.finish({ stopReason: "end_turn", sessionId: "s1" });

      expect(stdout.output).toBe("");
    });
  });

  describe("json mode", () => {
    it("buffers session updates and writes nothing until finish()", () => {
      const stdout = makeFakeStdout();
      const sink = createOutputSink("json", stdout);

      sink.onSessionUpdate(textUpdate("s1", "Hello, "));
      sink.onSessionUpdate(textUpdate("s1", "world"));

      expect(stdout.output).toBe("");
    });

    it("emits exactly one parseable JSON document with the concatenated text and finish() fields", () => {
      const stdout = makeFakeStdout();
      const sink = createOutputSink("json", stdout);

      sink.onSessionUpdate(textUpdate("s1", "Hello, "));
      sink.onSessionUpdate(textUpdate("s1", "world"));
      const usage = { totalTokens: 42, inputTokens: 30, outputTokens: 12 };
      sink.finish({ stopReason: "end_turn", usage, sessionId: "s1" });

      const parsed = JSON.parse(stdout.output);
      expect(parsed).toEqual({
        text: "Hello, world",
        stopReason: "end_turn",
        usage,
        sessionId: "s1",
      });
    });

    // Several adapter settle paths carry no usage. The key has to stay in the
    // document so a consumer reading usage.totalTokens sees null, not a crash.
    it("emits usage: null when the turn settled without usage", () => {
      const stdout = makeFakeStdout();
      const sink = createOutputSink("json", stdout);

      sink.finish({ stopReason: "cancelled", sessionId: "s1" });

      expect(JSON.parse(stdout.output)).toEqual({
        text: "",
        stopReason: "cancelled",
        usage: null,
        sessionId: "s1",
      });
    });

    it.each(ignoredUpdates("s1"))(
      "excludes $label updates from the concatenated text",
      ({ update }) => {
        const stdout = makeFakeStdout();
        const sink = createOutputSink("json", stdout);

        sink.onSessionUpdate(textUpdate("s1", "kept"));
        sink.onSessionUpdate(update);
        sink.onSessionUpdate(textUpdate("s1", " text"));
        sink.finish({ stopReason: "end_turn", sessionId: "s1" });

        const parsed = JSON.parse(stdout.output);
        expect(parsed.text).toBe("kept text");
      },
    );

    it('produces text: "" for an empty run with no session updates', () => {
      const stdout = makeFakeStdout();
      const sink = createOutputSink("json", stdout);

      sink.finish({ stopReason: "end_turn", sessionId: "s1" });

      const parsed = JSON.parse(stdout.output);
      expect(parsed.text).toBe("");
      expect(parsed.stopReason).toBe("end_turn");
      expect(parsed.sessionId).toBe("s1");
    });
  });
});
