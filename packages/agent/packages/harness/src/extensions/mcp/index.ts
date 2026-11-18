// Thin `index.ts` re-export used only as pi's `-e` extension entry point.
//
// pi's startup banner derives an extension's display name from its file
// path: a trailing `index.ts`/`index.js` segment is dropped in favor of the
// parent directory name, so loading this file (instead of `./extension.ts`
// directly) makes the extension show as `mcp` instead of `mcp/extension.js`.
// `./extension.ts` remains the real implementation per the convention in
// `../README.md`.
export { default } from "./extension";
