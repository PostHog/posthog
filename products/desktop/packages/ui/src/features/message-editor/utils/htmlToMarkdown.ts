/// <reference path="../../../types/joplin-turndown-plugin-gfm.d.ts" />
import { gfm } from "@joplin/turndown-plugin-gfm";
import TurndownService from "turndown";

let turndown: TurndownService | null = null;

export interface ClipboardHtmlConversion {
  text: string;
  kind: "markdown" | "plain";
}

const NON_CONTENT_TAGS = new Set([
  "HEAD",
  "LINK",
  "META",
  "SCRIPT",
  "STYLE",
  "TITLE",
]);

function getTurndown(): TurndownService {
  if (turndown) return turndown;
  turndown = new TurndownService({
    headingStyle: "atx",
    codeBlockStyle: "fenced",
    bulletListMarker: "-",
    emDelimiter: "*",
  });
  turndown.use(gfm); // tables, strikethrough, task lists
  // Drop non-content elements outright. macOS puts a <style> block in the
  // clipboard HTML when copying rich text from native apps (Notes, Mail,
  // Slack), and Turndown would otherwise emit its CSS as text, e.g.
  // "p.p1 {margin: 0.0px ...; font: 18.0px Helvetica}" before the real text.
  turndown.remove(["style", "script", "head", "title", "meta", "link"]);
  // The composer is plain-text, so we only want structural formatting
  // (headings, lists, links, tables, code) preserved as Markdown. Turndown's
  // default escaping is meant for round-tripping Markdown and mangles ordinary
  // text — "1." -> "1\.", "snake_case" -> "snake\_case", "[x]" -> "\[x\]".
  // Disabling it keeps plain text intact so it also stays equal to the
  // plain-text fallback below and defers to the editor's native paste.
  turndown.escape = (text) => text;
  return turndown;
}

/** Convert clipboard HTML to Markdown. Returns null when it adds nothing over the plain-text fallback. */
export function htmlToMarkdown(
  html: string,
  plainTextFallback?: string,
): string | null {
  const markdown = getTurndown().turndown(html).trim();
  if (!markdown) return null;

  // No formatting beyond the plain text; defer to the default paste.
  if (
    plainTextFallback !== undefined &&
    markdown === plainTextFallback.trim()
  ) {
    return null;
  }

  return markdown;
}

function containsOnlyOneCodeBlock(html: string): boolean {
  const document = new DOMParser().parseFromString(html, "text/html");
  const codeBlocks = document.body.querySelectorAll("pre");
  if (codeBlocks.length !== 1) return false;

  const codeBlock = codeBlocks[0];
  return Array.from(document.body.querySelectorAll("*")).every(
    (element) =>
      NON_CONTENT_TAGS.has(element.tagName) ||
      element === codeBlock ||
      element.contains(codeBlock) ||
      codeBlock.contains(element),
  );
}

export function convertClipboardHtml(
  html: string,
  plainTextFallback?: string,
): ClipboardHtmlConversion | null {
  if (plainTextFallback !== undefined && containsOnlyOneCodeBlock(html)) {
    return { text: plainTextFallback, kind: "plain" };
  }

  const markdown = htmlToMarkdown(html, plainTextFallback);
  return markdown ? { text: markdown, kind: "markdown" } : null;
}
