const FRONTMATTER = /^---\r?\n[\s\S]*?\r?\n---\r?\n?/;
const LEADING_TITLE = /^#[^#\n]*\r?\n?/;

/**
 * The page without its frontmatter block.
 *
 * The block is how agents and the repo lint find a page's project, space and
 * status. A reader gets none of that from `team_id: 1 channel_id: 8f2c…` sitting
 * above the first heading, so the rendered view drops it.
 */
export function stripFrontmatter(content: string): string {
  return content.replace(FRONTMATTER, "").trimStart();
}

/**
 * The page body without its top-level heading.
 *
 * A page written for the wiki repo opens with a heading naming the space it
 * belongs to. On the space's own page that name is already the title above, so
 * the heading reads as the same words twice.
 */
export function stripLeadingTitle(content: string): string {
  return content.replace(LEADING_TITLE, "").trimStart();
}

/** A page split into what the repo requires and what a person wrote. */
export interface PageParts {
  /** Frontmatter and the page's own heading, verbatim. */
  preamble: string;
  body: string;
}

/**
 * The page, split at the first line a person would want to edit.
 *
 * The repo lint requires the frontmatter, so an editor that shows it invites
 * deleting it and getting the save refused. Splitting it off means a person
 * edits their notes and the page keeps its contract.
 */
export function splitPageContent(content: string): PageParts {
  const frontmatter = content.match(FRONTMATTER)?.[0] ?? "";
  const rest = content.slice(frontmatter.length).trimStart();
  const title = rest.match(LEADING_TITLE)?.[0] ?? "";
  const head = frontmatter.trimEnd();
  const heading = title.trimEnd();
  return {
    preamble: head && heading ? `${head}\n\n${heading}` : head || heading,
    body: rest.slice(title.length).trimStart(),
  };
}

/** The page again, from its preamble and an edited body. */
export function joinPageContent(preamble: string, body: string): string {
  const written = body.trim();
  if (!preamble) return written ? `${written}\n` : "";
  return written ? `${preamble}\n\n${written}\n` : `${preamble}\n`;
}
