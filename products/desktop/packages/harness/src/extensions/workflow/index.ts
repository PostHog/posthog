// Thin `index.ts` re-export used only as pi's `-e` extension entry point, so
// the extension displays as `workflow` (parent directory name) instead of
// `workflow/extension.js`. `./extension.ts` is the real implementation.
export { default } from "./extension";
