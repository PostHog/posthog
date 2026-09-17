import { unescapeXmlAttr } from "@posthog/shared";

export const CHANNEL_CONTEXT_TAG = "channel_context";
export const CANVAS_INSTRUCTIONS_TAG = "canvas_generation_instructions";
export const CUSTOM_INSTRUCTIONS_TAG = "user_custom_instructions";
export const CUSTOM_INSTRUCTIONS_PREAMBLE =
  "The user has saved custom instructions that apply to all of their tasks. Follow them.";

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
  blocks: InjectedBlock[];
  text: string;
}

interface InjectedBlockSpec {
  kind: InjectedBlockKind;
  pattern: RegExp;
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
  spec(
    "posthog-context",
    ["posthog_trusted_context", "posthog_untrusted_context", "posthog_context"],
    { keepTags: true },
  ),
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
  return { blocks, text: text.trim() };
}

export function stripInjectedBlocks(content: string): string {
  return splitInjectedBlocks(content).text;
}

export function hasInjectedBlocks(content: string): boolean {
  return splitInjectedBlocks(content).blocks.length > 0;
}
