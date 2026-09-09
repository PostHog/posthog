import { describe, expect, it } from "vitest";
import { ClaudeTokenEventRedactor } from "./redact-claude-tokens";

describe("ClaudeTokenEventRedactor", () => {
  it.each(["agent_message_chunk", "agent_thought_chunk"])(
    "protects tokens at every split in %s and preserves other text",
    (sessionUpdate) => {
      const token = "sk-ant-oat01-fake-test-token";
      for (const text of [
        `Token: ${token}. Next.`,
        `${token} ${token}`,
        "Plain text with s, sk-ant-, and sk-ant-oat01.",
      ]) {
        for (let split = 1; split < text.length; split++) {
          const redactor = new ClaudeTokenEventRedactor();
          const events = [text.slice(0, split), text.slice(split)].flatMap(
            (part) =>
              redactor.redact({
                type: "notification",
                notification: {
                  method: "session/update",
                  params: {
                    update: {
                      sessionUpdate,
                      content: { type: "text", text: part },
                    },
                  },
                },
              }),
          );
          events.push(...redactor.redact({ type: "done" }));
          const result = events
            .map((event) => {
              const notification = event.notification as
                | { params: { update: { content: { text: string } } } }
                | undefined;
              return notification?.params.update.content.text ?? "";
            })
            .join("");
          expect(result).toBe(text.replaceAll(token, "[REDACTED]"));
          expect(JSON.stringify(events)).not.toContain("fake-test-token");
        }
      }
    },
  );
});
