import { describe, expect, it } from "vitest";
import { redactSecrets, SecretEventRedactor } from "./redact-secrets";
import { SECRET_HEADERS, TOKEN_RULES } from "./secret-rules";

const CHUNK_KINDS = ["agent_message_chunk", "agent_thought_chunk"];

const chunkCases: [string, string, string, string][] = TOKEN_RULES.flatMap(
  (rule) =>
    CHUNK_KINDS.map((sessionUpdate): [string, string, string, string] => [
      rule.label,
      sessionUpdate,
      `${rule.prefix}aaaa1111`,
      rule.prefix,
    ]),
);

const headerCases: [
  string,
  Record<string, unknown>,
  Record<string, unknown>,
][] = SECRET_HEADERS.flatMap((header) => [
  [
    `${header} name/value pair`,
    {
      headers: [
        { name: header, value: "Bearer leaked-value" },
        { name: "x-posthog-mcp-consumer", value: "cloud" },
      ],
    },
    {
      headers: [
        { name: header, value: "[REDACTED]" },
        { name: "x-posthog-mcp-consumer", value: "cloud" },
      ],
    },
  ],
  [
    `${header} map entry`,
    { headers: { [header]: "Bearer leaked-value", "x-id": "123" } },
    { headers: { [header]: "[REDACTED]", "x-id": "123" } },
  ],
]);

describe("redactSecrets", () => {
  it.each(chunkCases)(
    "protects a %s at every split in %s",
    (_label, sessionUpdate, token, prefix) => {
      for (const text of [
        `Token: ${token}. Next.`,
        `${token} ${token}`,
        `Plain text with ${prefix.slice(0, 1)}, and ${prefix.slice(0, -1)}.`,
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
          expect(JSON.stringify(events)).not.toContain("aaaa1111");
        }
      }
    },
  );

  it.each(headerCases)("redacts a %s", (_shape, server, expected) => {
    expect(
      redactSecrets({
        method: "session/new",
        params: { mcpServers: [server] },
      }),
    ).toEqual({ method: "session/new", params: { mcpServers: [expected] } });
  });
});
