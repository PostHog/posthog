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

  it("redacts every segment of a JWT", () => {
    const jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJhY2N0XzEifQ.c2lnbmF0dXJl";
    expect(redactSecrets(`Bearer ${jwt} ok`)).toBe("Bearer [REDACTED] ok");
    expect(redactSecrets(`Bearer ${jwt}. ok`)).toBe("Bearer [REDACTED]. ok");
  });

  it.each(headerCases)("redacts a %s", (_shape, server, expected) => {
    expect(
      redactSecrets({
        method: "session/new",
        params: { mcpServers: [server] },
      }),
    ).toEqual({ method: "session/new", params: { mcpServers: [expected] } });
  });

  it.each([
    ["an oauth access token", "Bearer pha_abcDEF123_-xyz", "Bearer [REDACTED]"],
    ["an oauth refresh token", "refresh=phr_abc123", "refresh=[REDACTED]"],
    [
      "a gateway session token",
      "token phe_abc123 used",
      "token [REDACTED] used",
    ],
    [
      "the auth proxy path token",
      `base http://127.0.0.1:53211/${"a".repeat(43)}/v1/messages`,
      "base http://127.0.0.1:53211/[REDACTED]/v1/messages",
    ],
  ])("redacts %s in a string", (_label, input, expected) => {
    expect(redactSecrets(input)).toBe(expected);
  });

  it("keeps words that only contain a token prefix", () => {
    expect(redactSecrets("alpha_blend graphe_x morphr_y")).toBe(
      "alpha_blend graphe_x morphr_y",
    );
    expect(streamText(["see alpha_blend here"])).toBe("see alpha_blend here");
  });

  it.each(TOKEN_RULES.map((rule) => rule.prefix))(
    "redacts %s after an escaped newline or a percent code",
    (prefix) => {
      expect(redactSecrets(`x\\n${prefix}aaaa1111`)).toBe("x\\n[REDACTED]");
      expect(redactSecrets(`Bearer%20${prefix}aaaa1111`)).toBe(
        "Bearer%20[REDACTED]",
      );
    },
  );

  it.each(TOKEN_RULES.map((rule) => [rule.prefix, !!rule.wordStart] as const))(
    "applies the word-start guard to %s only when flagged",
    (prefix, wordStart) => {
      const input = `x${prefix}aaaa1111`;
      expect(redactSecrets(input)).toBe(wordStart ? input : "x[REDACTED]");
    },
  );

  it("redacts a loopback URL followed by a multi-megabyte token run", () => {
    const input = `http://127.0.0.1:53211/${"a".repeat(6_000_000)}`;
    expect(redactSecrets(input)).toBe("http://127.0.0.1:53211/[REDACTED]");
  });

  it("redacts the proxy path token in chunks held for a partial prefix", () => {
    const url = `http://127.0.0.1:53211/${"a".repeat(43)}/v1`;
    const out = streamText(["first gh", ` ${url} gh`, " end"]);
    expect(out).not.toContain("a".repeat(43));
    expect(out).toContain("127.0.0.1:53211/[REDACTED]");
  });

  it.each(["127.0.0.1", "localhost", "[::1]"])(
    "redacts a %s proxy URL split at every boundary",
    (host) => {
      const token = `${"a".repeat(40)}Z9`;
      const text = `see http://${host}:53211/${token}/v1 now`;
      for (let cut = 1; cut < text.length; cut++) {
        const out = streamText([text.slice(0, cut), text.slice(cut)]);
        expect(out).toBe(`see http://${host}:53211/[REDACTED]/v1 now`);
      }
    },
  );

  it("redacts a proxy URL spread over many small chunks", () => {
    const text = `x http://127.0.0.1:53211/${"b".repeat(43)}/v1`;
    const parts = text.match(/.{1,3}/g) ?? [];
    expect(streamText(parts)).toBe("x http://127.0.0.1:53211/[REDACTED]/v1");
  });

  it("keeps short loopback paths such as the MCP proxy ids", () => {
    expect(redactSecrets("http://127.0.0.1:4000/posthog")).toBe(
      "http://127.0.0.1:4000/posthog",
    );
  });
});

function streamText(parts: string[]): string {
  const redactor = new SecretEventRedactor();
  const events = parts.flatMap((part) =>
    redactor.redact({
      type: "notification",
      notification: {
        method: "session/update",
        params: {
          update: {
            sessionUpdate: "agent_message_chunk",
            content: { type: "text", text: part },
          },
        },
      },
    }),
  );
  events.push(...redactor.redact({ type: "done" }));
  return events
    .map((event) => {
      const notification = event.notification as
        | { params: { update: { content: { text: string } } } }
        | undefined;
      return notification?.params.update.content.text ?? "";
    })
    .join("");
}
