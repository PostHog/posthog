import { existsSync } from "node:fs";
import { resolve as resolvePath } from "node:path";

/**
 * Resolve a shared dist asset relative to the compiled adapter location. When
 * bundled into different entry points (dist/agent.js, dist/server/bin.cjs,
 * dist/server/harness/bin.js, etc), `import.meta.dirname` sits at different
 * depths — and is unavailable in the CJS bin bundle, where `__dirname` takes
 * over. Walk up until the script is found so each bundle locates the asset.
 */
export function resolveBundledMcpScript(rel: string): string {
  let dir = import.meta.dirname ?? __dirname;
  for (let i = 0; i < 5; i++) {
    const candidate = resolvePath(dir, rel);
    if (existsSync(candidate)) return candidate;
    dir = resolvePath(dir, "..");
  }
  throw new Error(
    `Could not locate ${rel} relative to ${import.meta.dirname ?? __dirname}.`,
  );
}
