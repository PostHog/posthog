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

function textUpdate(sessionId: string, text: string) {
  return {
    sessionId,
    update: {
      sessionUpdate: "agent_message_chunk",
      content: { type: "text", text },
    },
  };
}

function ignoredUpdate(sessionId: string) {
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
      },
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

    it.each(ignoredUpdate("s1"))("ignores $label updates", ({ update }) => {
      const stdout = makeFakeStdout();
      const sink = createOutputSink("text", stdout);

      sink.onSessionUpdate(textUpdate("s1", "kept"));
      sink.onSessionUpdate(update);
      sink.onSessionUpdate(textUpdate("s1", " text"));

      expect(stdout.output).toBe("kept text");
    });

    it("does not emit a JSON document from finish()", () => {
      const stdout = makeFakeStdout();
      const sink = createOutputSink("text", stdout);

      sink.onSessionUpdate(textUpdate("s1", "some streamed text"));
      sink.finish({ stopReason: "end_turn", sessionId: "s1" });

      // Text mode must never buffer the streamed text into a finish-result
      // JSON document. Unparseable output is fine — that IS plain text.
      let parsed: unknown;
      try {
        parsed = JSON.parse(stdout.output);
      } catch {
        parsed = undefined;
      }
      const isFinishDocument =
        typeof parsed === "object" &&
        parsed !== null &&
        "text" in parsed &&
        "stopReason" in parsed;
      expect(isFinishDocument).toBe(false);
      expect(stdout.output).toContain("some streamed text");
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
      sink.finish({
        stopReason: "end_turn",
        usage: { totalTokens: 42 },
        sessionId: "s1",
      });

      const parsed = JSON.parse(stdout.output);
      expect(parsed).toEqual({
        text: "Hello, world",
        stopReason: "end_turn",
        usage: { totalTokens: 42 },
        sessionId: "s1",
      });
    });

    it.each(ignoredUpdate("s1"))(
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
