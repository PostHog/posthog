import {
  buildObjectTagRef,
  type ObjectTagRef,
  objectWebPath,
  parseObjectTagAttrs,
  resolveObjectKindName,
} from "@posthog/core/inbox/objectTags";
import type { Token, TokenizerExtension } from "marked";

// Agents embed PostHog objects in replies as tags, e.g.
//   <insight id="9pQx3">checkout funnel</insight>
//   <insight id="9pQx3" display="block"/>
//   <hogql display="block" title="DAU">SELECT ...</hogql>
// These marked extensions turn them into chip and card tokens. Code spans and
// fences are tokenized first, so tags inside them stay literal.

// Each card makes a request on mount; past the cap a block tag becomes a chip.
const MAX_CARDS = 10;

const TAG_RE =
  /^<([a-z][\w-]*)((?:\s+[a-z][\w-]*\s*=\s*"[^"]*")*)\s*(?:\/>|>([\s\S]*?)<\/\1\s*>)/;
const BLOCK_TAIL_RE = /^[ \t]*(?:\n+|$)/;
const TAG_START_RE = /<[a-z]/;
const MARKUP_RE = /^<\/?([a-z][\w-]*)/;

export type ObjectCardSpec =
  | { mode: "insight"; shortId: string; title?: string }
  | { mode: "hogql"; query: string; title?: string };

export interface ObjectCardToken {
  type: "objectCard";
  raw: string;
  spec: ObjectCardSpec;
}

export interface ObjectRefToken {
  type: "objectRef";
  raw: string;
  ref: ObjectTagRef;
}

interface MatchedTag {
  raw: string;
  name: string;
  kind: string | null;
  attrs: Record<string, string>;
  body?: string;
}

function matchTag(src: string): MatchedTag | null {
  const match = TAG_RE.exec(src);
  if (!match) return null;
  return {
    raw: match[0],
    name: match[1],
    kind: resolveObjectKindName(match[1]),
    attrs: parseObjectTagAttrs(match[2]),
    body: match[3],
  };
}

function cardSpec(tag: MatchedTag): ObjectCardSpec | null {
  if (tag.attrs.display !== "block") return null;
  const title = tag.attrs.title?.trim() || undefined;
  if (tag.kind === "insight") {
    const shortId = tag.attrs.id?.trim();
    return shortId ? { mode: "insight", shortId, title } : null;
  }
  if (tag.kind === "hogql") {
    const query = tag.body?.trim();
    return query ? { mode: "hogql", query, title } : null;
  }
  return null;
}

// An unknown kind is still an object tag when it carries an id.
function isObjectTag(tag: MatchedTag): boolean {
  return tag.kind !== null || "id" in tag.attrs;
}

// Unknown kinds, and known kinds without an id or query, keep only their label.
function inlineToken(tag: MatchedTag): Token {
  const ref = tag.kind
    ? buildObjectTagRef(tag.kind, tag.attrs, tag.body)
    : null;
  if (ref) return { type: "objectRef", raw: tag.raw, ref } as Token;
  const label = tag.kind ? "" : tag.body?.trim() || tag.attrs.label?.trim();
  return { type: "text", raw: tag.raw, text: label ?? "" };
}

// A fresh set per document, so the card cap counts one message at a time.
export function objectTagExtensions(): TokenizerExtension[] {
  let cards = 0;
  return [
    {
      name: "objectCard",
      level: "block",
      tokenizer(src) {
        const indent = /^ {0,3}/.exec(src)?.[0].length ?? 0;
        const tag = matchTag(src.slice(indent));
        if (!tag || !isObjectTag(tag)) return undefined;
        const end = indent + tag.raw.length;
        const tail = BLOCK_TAIL_RE.exec(src.slice(end));
        if (!tail) return undefined;
        const raw = src.slice(0, end + tail[0].length);
        const spec = cardSpec(tag);
        if (spec && cards < MAX_CARDS) {
          cards++;
          return { type: "objectCard", raw, spec };
        }
        return {
          type: "paragraph",
          raw,
          text: tag.raw,
          tokens: this.lexer.inlineTokens(tag.raw),
        };
      },
    },
    {
      name: "objectRef",
      level: "inline",
      start(src) {
        const index = src.search(TAG_START_RE);
        return index === -1 ? undefined : index;
      },
      tokenizer(src) {
        const tag = matchTag(src);
        return tag && isObjectTag(tag) ? inlineToken(tag) : undefined;
      },
    },
  ];
}

export function isObjectCardToken(
  token: Token,
): token is Token & ObjectCardToken {
  return token.type === "objectCard";
}

export function isObjectRefToken(
  token: Token,
): token is Token & ObjectRefToken {
  return token.type === "objectRef";
}

// Markup of a known tag that is malformed or still streaming stays hidden.
export function isObjectTagMarkup(html: string): boolean {
  const match = MARKUP_RE.exec(html.trim());
  return match !== null && resolveObjectKindName(match[1]) !== null;
}

export function objectWebUrl(
  host: string,
  projectId: number,
  kind: string,
  id: string,
): string | null {
  const path = objectWebPath(kind, id);
  return path
    ? `${host.replace(/\/+$/, "")}/project/${projectId}${path}`
    : null;
}
