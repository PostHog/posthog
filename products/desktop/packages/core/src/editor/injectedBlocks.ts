import { unescapeXmlAttr } from "@posthog/shared";

export const CHANNEL_CONTEXT_TAG = "channel_context";
export const CANVAS_INSTRUCTIONS_TAG = "canvas_generation_instructions";
export const CUSTOM_INSTRUCTIONS_TAG = "user_custom_instructions";
export const CUSTOM_INSTRUCTIONS_PREAMBLE =
  "The user has saved custom instructions that apply to all of their tasks. Follow them.";

// A block is text folded into a user message at send time that the user never
// typed: a channel's CONTEXT.md, the canvas authoring contract, the PostHog app
// context a web-app chat prepends, saved personalization, the first-run brief,
// a Slack thread. Every surface that shows a message peels them through
// `splitInjectedBlocks`, so a new kind is one entry here plus one presentation
// entry in @posthog/ui, and can never leak as raw XML through a surface that
// forgot it.
export type InjectedBlockKind =
  | "channel-context"
  | "canvas-instructions"
  | "posthog-context"
  | "custom-instructions"
  | "onboarding-brief"
  | "slack-thread";

export interface InjectedBlock {
  kind: InjectedBlockKind;
  body: string;
  attrs: Record<string, string>;
}

export interface InjectedBlockSplit {
  /** One block per kind, in registry order. */
  blocks: InjectedBlock[];
  text: string;
}

interface InjectedBlockSpec {
  kind: InjectedBlockKind;
  pattern: RegExp;
  /** Keep the tags in `body`, so a reader sees the element the agent saw. */
  keepTags: boolean;
  guard?: (inner: string) => boolean;
}

function spec(
  kind: InjectedBlockKind,
  tags: readonly string[],
  options: { keepTags?: boolean; guard?: (inner: string) => boolean } = {},
): InjectedBlockSpec {
  return {
    kind,
    pattern: new RegExp(
      `<(${tags.join("|")})\\b([^>]*)>([\\s\\S]*?)</\\1>`,
      "g",
    ),
    keepTags: options.keepTags ?? false,
    guard: options.guard,
  };
}

const INJECTED_BLOCK_SPECS: readonly InjectedBlockSpec[] = [
  spec("channel-context", [CHANNEL_CONTEXT_TAG]),
  spec("canvas-instructions", [CANVAS_INSTRUCTIONS_TAG]),
  // The web app's AI chat and the quick-ask panel prepend these; the trusted
  // and untrusted elements read as one block, tags included, because the split
  // between them is the point.
  spec(
    "posthog-context",
    ["posthog_trusted_context", "posthog_untrusted_context", "posthog_context"],
    { keepTags: true },
  ),
  // The tag alone is not proof of injection: a user can paste the same XML as
  // an example they want shown verbatim. Only the preamble the prompt builder
  // emits marks a block as ours.
  spec("custom-instructions", [CUSTOM_INSTRUCTIONS_TAG], {
    guard: (inner) =>
      inner.trimStart().startsWith(CUSTOM_INSTRUCTIONS_PREAMBLE),
  }),
  spec("onboarding-brief", ["onboarding_brief"]),
  spec("slack-thread", ["slack_thread_context"]),
];

function parseAttrs(raw: string): Record<string, string> {
  const attrs: Record<string, string> = {};
  for (const [, name, value] of raw.matchAll(/([\w:-]+)="([^"]*)"/g)) {
    attrs[name] = unescapeXmlAttr(value);
  }
  return attrs;
}

export function splitInjectedBlocks(content: string): InjectedBlockSplit {
  const blocks: InjectedBlock[] = [];
  let text = content;
  for (const { kind, pattern, keepTags, guard } of INJECTED_BLOCK_SPECS) {
    const bodies: string[] = [];
    let attrs: Record<string, string> | undefined;
    text = text.replace(
      pattern,
      (element: string, _tag: string, rawAttrs: string, inner: string) => {
        if (guard && !guard(inner)) return element;
        attrs ??= parseAttrs(rawAttrs);
        bodies.push(keepTags ? element : inner.trim());
        return "";
      },
    );
    if (bodies.length > 0) {
      blocks.push({ kind, body: bodies.join("\n"), attrs: attrs ?? {} });
    }
  }
  // Trim only. Every producer puts its blocks at one end of the prompt, so
  // removal leaves nothing but a newline run there; collapsing anything else
  // would edit the user's own text, and `text` is what renders, copies and
  // replays into the composer.
  return { blocks, text: text.trim() };
}

export function stripInjectedBlocks(content: string): string {
  return splitInjectedBlocks(content).text;
}

export function hasInjectedBlocks(content: string): boolean {
  return splitInjectedBlocks(content).blocks.length > 0;
}
