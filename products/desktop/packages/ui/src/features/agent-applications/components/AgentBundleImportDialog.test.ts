import { describe, expect, it } from "vitest";
import { type ParsedBundle, parseBundleInput } from "../utils/parseBundleInput";

type Expected =
  | { ok: true; value: ParsedBundle }
  | { ok: false; errorMatch?: RegExp };

const cases: Array<{ name: string; input: string; expected: Expected }> = [
  {
    name: "rejects empty input",
    input: "",
    expected: { ok: false },
  },
  {
    name: "parses a single agent.md block",
    input: "--- agent.md ---\nYou are the growth review agent.\n",
    expected: {
      ok: true,
      value: { agent_md: "You are the growth review agent." },
    },
  },
  {
    name: "parses multiple skill blocks",
    input: [
      "--- skills/research/SKILL.md ---",
      "Research body",
      "--- skills/draft-post/SKILL.md ---",
      "Draft body",
    ].join("\n"),
    expected: {
      ok: true,
      value: {
        skills: [
          { id: "research", body: "Research body" },
          { id: "draft-post", body: "Draft body" },
        ],
      },
    },
  },
  {
    name: "parses agent.md plus skills together",
    input: [
      "--- agent.md ---",
      "Main prompt",
      "",
      "--- skills/research/SKILL.md ---",
      "Research body",
    ].join("\n"),
    expected: {
      ok: true,
      value: {
        agent_md: "Main prompt",
        skills: [{ id: "research", body: "Research body" }],
      },
    },
  },
  {
    name: "tolerates CRLF line endings",
    input: "--- agent.md ---\r\nMain prompt\r\n",
    expected: { ok: true, value: { agent_md: "Main prompt" } },
  },
  {
    name: "rejects an unsupported file path",
    input: "--- tools/foo/source.ts ---\nconsole.log('hi')\n",
    expected: { ok: false, errorMatch: /Unsupported file path/ },
  },
  {
    name: "rejects skill ids with spaces",
    input: "--- skills/Bad Id/SKILL.md ---\nbody\n",
    expected: { ok: false },
  },
  {
    name: "rejects skill ids with uppercase letters",
    input: "--- skills/MySkill/SKILL.md ---\nbody\n",
    expected: { ok: false },
  },
  {
    name: "ignores leading content before the first header",
    input: [
      "# notes for myself, not in any block",
      "--- agent.md ---",
      "Prompt",
    ].join("\n"),
    expected: { ok: true, value: { agent_md: "Prompt" } },
  },
];

describe("parseBundleInput", () => {
  it.each(cases)("$name", ({ input, expected }) => {
    const out = parseBundleInput(input);
    if (expected.ok) {
      expect(out).toEqual(expected);
      return;
    }
    expect(out.ok).toBe(false);
    if (!out.ok && expected.errorMatch) {
      expect(out.error).toMatch(expected.errorMatch);
    }
  });
});
