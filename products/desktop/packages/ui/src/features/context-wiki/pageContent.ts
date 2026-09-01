const FRONTMATTER = /^---\r?\n[\s\S]*?\r?\n---\r?\n?/;

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
