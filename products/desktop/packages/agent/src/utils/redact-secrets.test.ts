import { describe, expect, it } from "vitest";
import { redactSecrets, SecretEventRedactor } from "./redact-secrets";

describe("redactSecrets", () => {
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
          const redactor = new SecretEventRedactor();
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

  it.each([
    [
      "name/value header pairs",
      {
        headers: [
          { name: "Authorization", value: "Bearer pair-secret" },
          { name: "x-posthog-mcp-consumer", value: "cloud" },
        ],
      },
      {
        headers: [
          { name: "Authorization", value: "[REDACTED]" },
          { name: "x-posthog-mcp-consumer", value: "cloud" },
        ],
      },
    ],
    [
      "a header map",
      { headers: { authorization: "Bearer map-secret", "x-id": "123" } },
      { headers: { authorization: "[REDACTED]", "x-id": "123" } },
    ],
  ])("redacts authorization values in %s", (_shape, server, expected) => {
    expect(
      redactSecrets({
        method: "session/new",
        params: { mcpServers: [server] },
      }),
    ).toEqual({ method: "session/new", params: { mcpServers: [expected] } });
  });
});
