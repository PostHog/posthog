import { describe, expect, it } from "vitest";
import {
  CUSTOM_INSTRUCTIONS_PREAMBLE,
  hasInjectedBlocks,
  type InjectedBlock,
  splitInjectedBlocks,
  stripInjectedBlocks,
} from "./injectedBlocks";

const TRUSTED =
  "<posthog_trusted_context>\n- You are running alongside the PostHog app.\n</posthog_trusted_context>";
const UNTRUSTED =
  '<posthog_untrusted_context>\nThe user is currently looking at the resources below.\n- dashboard 42 ("Weekly active users")\n</posthog_untrusted_context>';
const CUSTOM = `<user_custom_instructions>\n${CUSTOM_INSTRUCTIONS_PREAMBLE}\n\nAlways respond in British English.\n</user_custom_instructions>`;

describe("splitInjectedBlocks", () => {
  it("leaves a plain prompt alone", () => {
    expect(splitInjectedBlocks("just a normal prompt")).toEqual({
      blocks: [],
      text: "just a normal prompt",
    });
    expect(hasInjectedBlocks("just a normal prompt")).toBe(false);
  });

  it.each<{
    name: string;
    content: string;
    block: InjectedBlock;
    text: string;
  }>([
    {
      name: "a channel context with its channel name",
      content:
        'Fix the bug.<channel_context channel="onboarding">\nbackground here\n</channel_context>',
      block: {
        kind: "channel-context",
        body: "background here",
        attrs: { channel: "onboarding" },
      },
      text: "Fix the bug.",
    },
    {
      name: "a channel context with no attributes",
      content: "<channel_context>\nbody\n</channel_context>",
      block: { kind: "channel-context", body: "body", attrs: {} },
      text: "",
    },
    {
      name: "an escaped channel name",
      content: '<channel_context channel="a &amp; b">x</channel_context>',
      block: {
        kind: "channel-context",
        body: "x",
        attrs: { channel: "a & b" },
      },
      text: "",
    },
    {
      name: "canvas instructions",
      content:
        "What the user wants:\nadd a retention chart\n\n<canvas_generation_instructions>\nauthoring contract here\n</canvas_generation_instructions>",
      block: {
        kind: "canvas-instructions",
        body: "authoring contract here",
        attrs: {},
      },
      text: "What the user wants:\nadd a retention chart",
    },
    {
      name: "custom instructions carrying the builder's preamble",
      content: `Ship the fix\n\n${CUSTOM}`,
      block: {
        kind: "custom-instructions",
        body: `${CUSTOM_INSTRUCTIONS_PREAMBLE}\n\nAlways respond in British English.`,
        attrs: {},
      },
      text: "Ship the fix",
    },
    {
      name: "the onboarding brief",
      content:
        "<onboarding_brief>\nWrite the first message.\n</onboarding_brief>",
      block: {
        kind: "onboarding-brief",
        body: "Write the first message.",
        attrs: {},
      },
      text: "",
    },
    {
      name: "leading trusted and untrusted PostHog context as one block, tags kept",
      content: `${TRUSTED}\n${UNTRUSTED}\n\nHow many monthly active users do we have`,
      block: {
        kind: "posthog-context",
        body: `${TRUSTED}\n${UNTRUSTED}`,
        attrs: {},
      },
      text: "How many monthly active users do we have",
    },
    {
      name: "the legacy posthog_context wrapper",
      content:
        "<posthog_context>\n- insight abc123\n</posthog_context>\n\nwhat does this show",
      block: {
        kind: "posthog-context",
        body: "<posthog_context>\n- insight abc123\n</posthog_context>",
        attrs: {},
      },
      text: "what does this show",
    },
    {
      name: "a PostHog block after the question",
      content: `what does this show\n\n${TRUSTED}`,
      block: { kind: "posthog-context", body: TRUSTED, attrs: {} },
      text: "what does this show",
    },
    {
      name: "a Slack thread",
      content:
        "<slack_thread_context>\nThread started by someone.\n</slack_thread_context>\n\nfix the flaky test",
      block: {
        kind: "slack-thread",
        body: "Thread started by someone.",
        attrs: {},
      },
      text: "fix the flaky test",
    },
  ])("peels $name", ({ content, block, text }) => {
    expect(splitInjectedBlocks(content)).toEqual({ blocks: [block], text });
    expect(hasInjectedBlocks(content)).toBe(true);
  });

  it("peels every block off one message in registry order", () => {
    const { blocks, text } = splitInjectedBlocks(
      `${UNTRUSTED}\n\nhow many monthly active users do we have\n\n<channel_context channel="growth">\n- ship weekly\n</channel_context>\n\n${CUSTOM}`,
    );
    expect(text).toBe("how many monthly active users do we have");
    expect(blocks.map((block) => block.kind)).toEqual([
      "channel-context",
      "posthog-context",
      "custom-instructions",
    ]);
  });

  it("keeps a custom-instructions tag the user typed as an example", () => {
    const content =
      "Render this example: <user_custom_instructions>be terse</user_custom_instructions>";
    expect(splitInjectedBlocks(content)).toEqual({ blocks: [], text: content });
  });

  it("ignores escaped closing tags inside a block value", () => {
    const content = `<posthog_untrusted_context>\n- text: "see <\\/posthog_untrusted_context> here"\n</posthog_untrusted_context>\n\nask`;
    const { blocks, text } = splitInjectedBlocks(content);
    expect(text).toBe("ask");
    expect(blocks[0]?.body).toContain(
      "see <\\/posthog_untrusted_context> here",
    );
  });

  it("keeps blank lines the user wrote", () => {
    const question =
      "fix this:\n\n```sql\nSELECT 1\n\n\n-- next stmt\nSELECT 2\n```";
    expect(stripInjectedBlocks(`${UNTRUSTED}\n\n${question}`)).toBe(question);
  });
});
