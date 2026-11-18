const MARKDOWN_LINK = /\[([^\]]+)\]\(\s*(?:https?:\/\/)?[^)\s]*\s*\)/g;
const LABELED_LINK = /<(?:https?:\/\/[^>|\s]+)\|([^>]*)>/g;
const BARE_LINK = /<(https?:\/\/[^>\s]+)>/g;
const CODE_FENCE = /```+/g;
const BACKTICK = /`/g;
const WHITESPACE = /\s+/g;

export function singleLineTitle(title: string): string {
  return title
    .replace(MARKDOWN_LINK, "$1")
    .replace(LABELED_LINK, "$1")
    .replace(BARE_LINK, "$1")
    .replace(CODE_FENCE, " ")
    .replace(BACKTICK, "")
    .replace(WHITESPACE, " ")
    .trim();
}
