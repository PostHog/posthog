import type { UserBasic } from "@posthog/shared/domain-types";
import { getSchema } from "@tiptap/core";
import Mention from "@tiptap/extension-mention";
import { Node as PmNode } from "@tiptap/pm/model";
import StarterKit from "@tiptap/starter-kit";
import { describe, expect, it } from "vitest";
import {
  contentToDoc,
  docToContent,
  filterComposerMentionCandidates,
  filterMentionCandidates,
} from "./mentionComposer";

function member(overrides: Partial<UserBasic> & { email: string }): UserBasic {
  return {
    id: 1,
    uuid: overrides.email,
    first_name: "",
    last_name: "",
    ...overrides,
  };
}

const ann = member({
  email: "ann@posthog.com",
  first_name: "Ann",
  last_name: "Lee",
});
const bob = member({
  email: "bob@posthog.com",
  first_name: "Bob",
  last_name: "Stone",
});
const raquel = member({
  email: "raquel@posthog.com",
  first_name: "Raquel",
  last_name: "Smith",
});
const members = [ann, bob, raquel];

describe("filterMentionCandidates", () => {
  it("returns everyone for an empty query", () => {
    expect(filterMentionCandidates(members, "")).toEqual([ann, bob, raquel]);
  });

  it("ranks name prefix over word prefix over email over substring", () => {
    const smithers = member({
      email: "s@posthog.com",
      first_name: "Smi",
      last_name: "Thers",
    });
    expect(filterMentionCandidates([...members, smithers], "sm")).toEqual([
      smithers, // name prefix
      raquel, // last-name word prefix
    ]);
  });

  it("matches by email", () => {
    expect(filterMentionCandidates(members, "bob@")).toEqual([bob]);
  });

  it("is case-insensitive and respects the limit", () => {
    expect(filterMentionCandidates(members, "RAQ")).toEqual([raquel]);
    expect(filterMentionCandidates(members, "", 2)).toHaveLength(2);
  });

  it("returns empty when nothing matches", () => {
    expect(filterMentionCandidates(members, "zzz")).toEqual([]);
  });
});

describe("filterComposerMentionCandidates", () => {
  it("offers the agent before matching teammates when enabled", () => {
    expect(filterComposerMentionCandidates(members, "a", true)).toEqual([
      { kind: "agent" },
      { kind: "member", member: ann },
      { kind: "member", member: raquel },
    ]);
  });

  it("does not offer the agent when forwarding is unavailable", () => {
    expect(filterComposerMentionCandidates(members, "agent", false)).toEqual(
      [],
    );
  });
});

describe("contentToDoc / docToContent", () => {
  const schema = getSchema([StarterKit, Mention]);

  function roundTrip(content: string): string {
    return docToContent(PmNode.fromJSON(schema, contentToDoc(content)));
  }

  it.each([
    ["plain text", "hello there"],
    ["empty content", ""],
    ["mention token", "hey @[Raquel Smith](raquel@posthog.com) hi"],
    [
      "multiple mentions",
      "@[Ann Lee](ann@posthog.com) @[Bob Stone](bob@posthog.com)",
    ],
    ["multi-line", "first\nsecond\n\nfourth"],
    ["mention across lines", "cc @[Ann Lee](ann@posthog.com)\nthanks"],
  ])("round-trips %s", (_label, content) => {
    expect(roundTrip(content)).toBe(content);
  });

  it("maps mention tokens to mention nodes with email as id", () => {
    const doc = contentToDoc("hi @[Ann Lee](ann@posthog.com)");
    expect(doc.content?.[0]?.content).toEqual([
      { type: "text", text: "hi " },
      {
        type: "mention",
        attrs: { id: "ann@posthog.com", label: "Ann Lee" },
      },
    ]);
  });

  it("serializes hard breaks as newlines", () => {
    const doc = PmNode.fromJSON(schema, {
      type: "doc",
      content: [
        {
          type: "paragraph",
          content: [
            { type: "text", text: "one" },
            { type: "hardBreak" },
            { type: "text", text: "two" },
          ],
        },
      ],
    });
    expect(docToContent(doc)).toBe("one\ntwo");
  });
});
