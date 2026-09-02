import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import type { PluggableList } from "unified";

/**
 * GitHub comment bodies are GitHub-flavored markdown with raw HTML baked in
 * (suggestion blocks, `<details>`, `<img>`, `<sub>`…). react-markdown drops raw
 * HTML by default, which leaves stray `</a>` fragments in the text — so parse
 * it with rehype-raw and sanitize what comes out.
 */
export const githubRehypePlugins: PluggableList = [
  rehypeRaw,
  [rehypeSanitize, defaultSchema],
];
