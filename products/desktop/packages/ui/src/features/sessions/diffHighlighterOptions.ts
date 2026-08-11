/**
 * Diff highlighter options shared by the session transcript views.
 * `tokenizeMaxLineLength` caps tokenization so a minified or single-giant-line
 * file can't stall diff highlighting.
 */
export const DIFFS_HIGHLIGHTER_OPTIONS = {
  theme: { dark: "github-dark" as const, light: "github-light" as const },
  tokenizeMaxLineLength: 1000,
};
