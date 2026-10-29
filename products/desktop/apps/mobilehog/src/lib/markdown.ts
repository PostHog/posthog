import { isSafeExternalUrl } from "@posthog/shared";
import { Marked, type Token, type Tokens } from "marked";
import { objectTagExtensions } from "@/lib/objectTags";

export type InlineRun =
  | { kind: "text"; tokens: Token[] }
  | { kind: "image"; token: Tokens.Image };

type Piece =
  | { kind: "text"; token: Token }
  | { kind: "image"; token: Tokens.Image };

export function isImageToken(token: Token): token is Tokens.Image {
  return token.type === "image";
}

export function isLoadableImageUrl(href: string): boolean {
  return /^https?:/i.test(href) && isSafeExternalUrl(href);
}

function isFormatToken(
  token: Token,
): token is Tokens.Strong | Tokens.Em | Tokens.Del {
  return token.type === "strong" || token.type === "em" || token.type === "del";
}

// Links stay whole, so an image inside a link keeps its alt text inline.
function liftImages(token: Token): Piece[] {
  if (isImageToken(token) && isLoadableImageUrl(token.href)) {
    return [{ kind: "image", token }];
  }
  if (!isFormatToken(token)) return [{ kind: "text", token }];
  const inner = token.tokens.flatMap(liftImages);
  if (!inner.some((piece) => piece.kind === "image")) {
    return [{ kind: "text", token }];
  }
  // Split the wrapper around each image so the text keeps its formatting.
  const pieces: Piece[] = [];
  let text: Token[] = [];
  const flush = () => {
    if (text.length) {
      const raw = text.map((child) => child.raw).join("");
      pieces.push({
        kind: "text",
        token: { ...token, raw, text: raw, tokens: text },
      });
    }
    text = [];
  };
  for (const piece of inner) {
    if (piece.kind === "image") {
      flush();
      pieces.push(piece);
    } else {
      text.push(piece.token);
    }
  }
  flush();
  return pieces;
}

// Images that can load stand on their own row between the text around them;
// the rest stay inline and render their alt text.
export function splitImageRuns(tokens: Token[]): InlineRun[] {
  const runs: InlineRun[] = [];
  let text: Token[] = [];
  const flush = () => {
    if (text.some((token) => token.raw.trim())) {
      runs.push({ kind: "text", tokens: text });
    }
    text = [];
  };
  for (const piece of tokens.flatMap(liftImages)) {
    if (piece.kind === "image") {
      flush();
      runs.push(piece);
    } else {
      text.push(piece.token);
    }
  }
  flush();
  return runs;
}

export function lexMarkdown(text: string): Token[] {
  const markdown = new Marked({ extensions: objectTagExtensions() });
  return markdown.Lexer.lex(text, markdown.defaults);
}
