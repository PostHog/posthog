// The @posthog/agent dist bundles open with tsup's Node shim:
//   import { createRequire } from "node:module"; const require = createRequire(import.meta.url);
// In the browser that import resolves to an empty module and every story in
// the chunk dies at load. Stories only use pure helpers from those bundles, so
// a require that throws on use is safe.
export function createRequire(): (id: string) => never {
  return (id: string) => {
    throw new Error(`require("${id}") is not available in Storybook`);
  };
}

export default { createRequire };
