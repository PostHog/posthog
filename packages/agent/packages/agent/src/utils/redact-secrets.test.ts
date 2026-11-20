import { describe, expect, it, vi } from "vitest";
import { POSTHOG_NOTIFICATIONS } from "../acp-extensions";
import {
  redactSecrets,
  SecretEventRedactor,
  secretHeaderReplacer,
} from "./redact-secrets";
import { SECRET_HEADERS, TOKEN_RULES, type TokenRule } from "./secret-rules";

const CHUNK_KINDS = ["agent_message_chunk", "agent_thought_chunk"];

const SAMPLE_BODY = "AAAA1111AAAA1111";

// A shaped rule matches a complete string only in its full shape.
function sampleToken(rule: TokenRule): string {
  return rule.shape
    ? `${rule.prefix}aaaa.1111`
    : `${rule.prefix}${SAMPLE_BODY}`;
}

const awsKeyBody = "B2".repeat(8);

const awsCases: [string, string, string][] = [
  ["bare ASIA", "ASIA", "ASIA"],
  ["ASIAN MARKETS", "ASIAN MARKETS", "ASIAN MARKETS"],
  ["ASIAPAC", "ASIAPAC", "ASIAPAC"],
  ["ASIA_PACIFIC", "ASIA_PACIFIC", "ASIA_PACIFIC"],
  ["ASIA in a sentence", "see ASIA today", "see ASIA today"],
  ["AKIRA", "AKIRA Kurosawa", "AKIRA Kurosawa"],
  ["bare AKIA", "AKIA", "AKIA"],
  ...["AKIA", "ASIA"].flatMap((prefix): [string, string, string][] => {
    const key = `${prefix}${awsKeyBody}`;
    return [
      [
        `a ${prefix} key id mid-sentence`,
        `use ${key} now`,
        "use [REDACTED] now",
      ],
      [`a ${prefix} key id ending the stream`, `id ${key}`, "id [REDACTED]"],
      [
        `a ${prefix} key id followed by capitals`,
        `${key}EXTRA`,
        "[REDACTED]EXTRA",
      ],
      [
        `a ${prefix} key id with a short body`,
        `${key.slice(0, -1)} end`,
        `${key.slice(0, -1)} end`,
      ],
      [`a ${prefix} key id inside a word`, `x${key}`, `x${key}`],
    ];
  }),
];

const chunkCases: [string, string, string, string][] = TOKEN_RULES.flatMap(
  (rule) =>
    CHUNK_KINDS.map((sessionUpdate): [string, string, string, string] => [
      rule.label,
      sessionUpdate,
      `${rule.prefix}${SAMPLE_BODY}`,
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
  [
    `${header} array map entry`,
    { headers: { [header]: ["Bearer leaked-value"], "x-id": "123" } },
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
          expect(JSON.stringify(events)).not.toContain(SAMPLE_BODY);
        }
      }
    },
  );

  it("redacts the resolved GitLab credential in output and across every stream split", () => {
    for (const token of ["custom+gitlab/token", "phx_custom-secret"]) {
      vi.stubEnv("GITLAB_TOKEN", token);
      try {
        for (const credential of [token, encodeURIComponent(token)]) {
          const text = `remote https://oauth2:${credential}@gitlab.com/group/repo.git`;
          const expected =
            "remote https://oauth2:[REDACTED]@gitlab.com/group/repo.git";
          expect(redactSecrets(text)).toBe(expected);
          for (let cut = 1; cut < text.length; cut++) {
            expect(streamText([text.slice(0, cut), text.slice(cut)])).toBe(
              expected,
            );
          }
        }
      } finally {
        vi.unstubAllEnvs();
      }
    }
  });

  it("preserves generic token redaction when a GitLab prefix overlaps a chunk", () => {
    vi.stubEnv("GITLAB_TOKEN", "glpat-example-secret");
    expect(streamText(["phx_g", "Abc123 "])).toBe("[REDACTED] ");
    vi.unstubAllEnvs();
  });

  it("redacts every segment of a JWT", () => {
    const jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJhY2N0XzEifQ.c2lnbmF0dXJl";
    expect(redactSecrets(`Bearer ${jwt} ok`)).toBe("Bearer [REDACTED] ok");
    expect(redactSecrets(`Bearer ${jwt}. ok`)).toBe("Bearer [REDACTED]. ok");
  });

  it("keeps a tool call id that contains the JWT prefix", () => {
    const update = {
      sessionUpdate: "tool_call",
      toolCallId: "toolu_01AbCdEfGheyJ4mQ7xZp2Wv9Ls",
    };
    expect(redactSecrets(update)).toEqual(update);
  });

  it.each(headerCases)("redacts a %s", (_shape, server, expected) => {
    expect(
      redactSecrets({
        method: "session/new",
        params: { mcpServers: [server] },
      }),
    ).toEqual({ method: "session/new", params: { mcpServers: [expected] } });
  });

  it.each(headerCases)(
    "masks a %s in JSON output",
    (_shape, server, expected) => {
      expect(JSON.parse(JSON.stringify(server, secretHeaderReplacer))).toEqual(
        expected,
      );
    },
  );

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

  it.each([
    ["gho_", 36],
    ["ghu_", 36],
    ["ghr_", 36],
    ["sk-proj-", 48],
    ["AKIA", 16],
    ["ASIA", 16],
    ["xoxb-", 30],
    ["xoxp-", 30],
    ["xoxa-", 30],
    ["xoxr-", 30],
    ["xoxs-", 30],
    ["xoxe-1-", 30],
    ["glpat-", 20],
  ])(
    "redacts a %s token whole and at every chunk split, not inside a word",
    (prefix, length) => {
      const token = prefix + "A".repeat(length);
      const text = `KEY=${token} end`;
      expect(redactSecrets(text)).toBe("KEY=[REDACTED] end");
      for (let cut = 1; cut < text.length; cut++) {
        expect(streamText([text.slice(0, cut), text.slice(cut)])).toBe(
          "KEY=[REDACTED] end",
        );
      }
      expect(redactSecrets(`x${token}`)).toBe(`x${token}`);
    },
  );

  it.each([
    ["a github oauth token", "ghost_story and gho"],
    ["a github user-to-server token", "ghulam_khan and ghu"],
    ["a github refresh token", "ghrelin_level and ghr"],
    ["an openai project api key", "sk-projects-list and sk-pro"],
    ["an aws access key id", "AKIRA Kurosawa and AKI"],
    ["an aws temporary access key id", "ASIAN markets and ASI"],
    ["a slack bot token", "xoxo-hugs and xoxb"],
    ["a slack user token", "xoxo-hugs and xoxp"],
    ["a slack legacy workspace token", "xoxo-hugs and xoxa"],
    ["a slack refresh token", "xoxo-hugs and xoxr"],
    ["a slack legacy session token", "xoxo-hugs and xoxs"],
    ["a slack rotation refresh token", "xoxo-hugs and xoxe"],
    ["a gitlab personal access token", "glpa-style and glpat"],
  ])("keeps a lookalike of %s intact at every chunk split", (_label, text) => {
    expect(redactSecrets(text)).toBe(text);
    for (let cut = 1; cut < text.length; cut++) {
      expect(streamText([text.slice(0, cut), text.slice(cut)])).toBe(text);
    }
  });

  it.each(["xoxp-", "xoxb-"])(
    "redacts the secret part of a rotated slack %s access token",
    (prefix) => {
      const text = `KEY=xoxe.${prefix}1-${"A".repeat(30)} end`;
      expect(redactSecrets(text)).toBe("KEY=xoxe.[REDACTED] end");
      for (let cut = 1; cut < text.length; cut++) {
        expect(streamText([text.slice(0, cut), text.slice(cut)])).toBe(
          "KEY=xoxe.[REDACTED] end",
        );
      }
    },
  );

  it.each(awsCases)(
    "treats %s the same whole and streamed",
    (_label, input, expected) => {
      expect(redactSecrets(input)).toBe(expected);
      expect(streamText([input])).toBe(expected);
      for (let cut = 1; cut < input.length; cut++) {
        expect(streamText([input.slice(0, cut), input.slice(cut)])).toBe(
          expected,
        );
      }
    },
  );

  it.each([
    ["an AKIA key id", "", `id AKIA${awsKeyBody} end`, "id [REDACTED] end"],
    ["an ASIA key id", "", `id ASIA${awsKeyBody} end`, "id [REDACTED] end"],
    [
      "a key id that ends like the GitLab credential starts",
      `2${"a".repeat(63)}`,
      `id ASIA${awsKeyBody}`,
      "id [REDACTED]",
    ],
    [
      "a token prefix that ends like the GitLab credential starts",
      `_${"a".repeat(19)}`,
      `id ghp_${SAMPLE_BODY} end`,
      "id [REDACTED] end",
    ],
  ])(
    "redacts %s split over three chunks",
    (_label, gitlabToken, text, expected) => {
      vi.stubEnv("GITLAB_TOKEN", gitlabToken);
      try {
        for (let first = 1; first < text.length; first++) {
          for (let second = first + 1; second < text.length; second++) {
            expect(
              streamText([
                text.slice(0, first),
                text.slice(first, second),
                text.slice(second),
              ]),
            ).toBe(expected);
          }
        }
      } finally {
        vi.unstubAllEnvs();
      }
    },
  );

  it.each([
    ["a token", `tok ghp_${SAMPLE_BODY} end`, "tok [REDACTED] end"],
    ["a key id", `id AKIA${awsKeyBody} end`, "id [REDACTED] end"],
  ])(
    "redacts %s split by a log line at every point",
    (_label, text, expected) => {
      const logLine = {
        event: {
          type: "notification",
          notification: {
            method: POSTHOG_NOTIFICATIONS.CONSOLE,
            params: { level: "debug", message: "tick" },
          },
        },
      };
      for (let cut = 1; cut < text.length; cut++) {
        expect(streamText([text.slice(0, cut), logLine, text.slice(cut)])).toBe(
          expected,
        );
      }
    },
  );

  it("keeps the text that follows a token and a tool call", () => {
    const toolCall = {
      event: {
        type: "notification",
        notification: {
          method: "session/update",
          params: {
            update: { sessionUpdate: "tool_call", toolCallId: "call" },
          },
        },
      },
    };
    expect(streamText([`tok ghp_${SAMPLE_BODY}`, toolCall, "Done"])).toBe(
      "tok [REDACTED]Done",
    );
  });

  it("keeps a prefix-bearing word intact across every chunk split", () => {
    const text = "see alpha_blend graphe_x here";
    for (let cut = 1; cut < text.length; cut++) {
      expect(streamText([text.slice(0, cut), text.slice(cut)])).toBe(text);
    }
  });

  it.each(TOKEN_RULES.filter((rule) => rule.wordStart).map((r) => r.prefix))(
    "redacts an escaped %s token split at every point",
    (prefix) => {
      for (const text of [
        `x%3D${prefix}${SAMPLE_BODY} end`,
        `x\\n${prefix}${SAMPLE_BODY} end`,
        `x\u001b[1;32m${prefix}${SAMPLE_BODY} end`,
        `x\\u001b[32m${prefix}${SAMPLE_BODY} end`,
        `x\\u00e9${prefix}${SAMPLE_BODY} end`,
        `x\\xe9${prefix}${SAMPLE_BODY} end`,
        `x\u001b[${"1;".repeat(40)}32m${prefix}${SAMPLE_BODY} end`,
        `x\\u001b[${"1;".repeat(40)}32m${prefix}${SAMPLE_BODY} end`,
      ]) {
        for (let cut = 1; cut < text.length; cut++) {
          const out = streamText([text.slice(0, cut), text.slice(cut)]);
          expect(out).not.toContain(SAMPLE_BODY);
        }
      }
    },
  );

  it("keeps a long colour code's opener when a partial prefix is held", () => {
    const colour = `\u001b[${"1;".repeat(40)}32m`;
    const out = streamText(["x p", `${colour}ph`, `a_${SAMPLE_BODY} end`]);
    expect(out).not.toContain(SAMPLE_BODY);
  });

  it("keeps the word check across a held prefix released with new text", () => {
    expect(streamText(["x p", "ing alp", "ha_blend end"])).toBe(
      "x ping alpha_blend end",
    );
  });

  it("does not carry one chunk kind's text into the next kind's word check", () => {
    const token = `pha_${"a".repeat(43)}`;
    expect(
      streamText([
        { kind: "agent_message_chunk", text: "see al" },
        { kind: "agent_thought_chunk", text: `${token} end` },
      ]),
    ).toBe("see al[REDACTED] end");
  });

  it.each(TOKEN_RULES.map((rule) => [rule.prefix, sampleToken(rule)]))(
    "redacts %s after an escaped newline or a percent code",
    (_prefix, token) => {
      expect(redactSecrets(`x\\n${token}`)).toBe("x\\n[REDACTED]");
      expect(redactSecrets(`Bearer%20${token}`)).toBe("Bearer%20[REDACTED]");
    },
  );

  it.each(
    TOKEN_RULES.map(
      (rule) => [rule.prefix, sampleToken(rule), !!rule.wordStart] as const,
    ),
  )(
    "applies the word-start guard to %s only when flagged",
    (_prefix, token, wordStart) => {
      const input = `x${token}`;
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

  it("redacts a loopback token when a GitLab prefix is buffered", () => {
    const previous = process.env.GITLAB_TOKEN;
    process.env.GITLAB_TOKEN = "glpat-example-secret";
    try {
      expect(
        streamText([
          `http://127.0.0.1:53211/${"A".repeat(31)}`,
          "g",
          `${"Z".repeat(11)}/v1`,
        ]),
      ).toBe("http://127.0.0.1:53211/[REDACTED]/v1");
    } finally {
      if (previous === undefined) delete process.env.GITLAB_TOKEN;
      else process.env.GITLAB_TOKEN = previous;
    }
  });

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

type StreamPart =
  | string
  | { kind: string; text: string }
  | { event: Record<string, unknown> };

function streamEvent(part: StreamPart): Record<string, unknown> {
  if (typeof part === "object" && "event" in part) return part.event;
  return {
    type: "notification",
    notification: {
      method: "session/update",
      params: {
        update: {
          sessionUpdate:
            typeof part === "string" ? "agent_message_chunk" : part.kind,
          content: {
            type: "text",
            text: typeof part === "string" ? part : part.text,
          },
        },
      },
    },
  };
}

function streamText(parts: StreamPart[]): string {
  const redactor = new SecretEventRedactor();
  const events = parts.flatMap((part) => redactor.redact(streamEvent(part)));
  events.push(...redactor.redact({ type: "done" }));
  return events
    .map((event) => {
      const notification = event.notification as
        | { params?: { update?: { content?: { text?: string } } } }
        | undefined;
      return notification?.params?.update?.content?.text ?? "";
    })
    .join("");
}
