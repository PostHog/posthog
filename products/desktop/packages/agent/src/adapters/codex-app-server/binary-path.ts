import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import { basename, dirname, join } from "node:path";

/**
 * Node `platform-arch` → codex target triple + `@openai/codex` platform sub-package
 * that vendors the native binary. Mirrors `@openai/codex`'s own `bin/codex.js` shim.
 */
const CODEX_NATIVE_TARGETS: Record<
  string,
  { triple: string; pkg: string } | undefined
> = {
  "linux-x64": {
    triple: "x86_64-unknown-linux-musl",
    pkg: "@openai/codex-linux-x64",
  },
  "linux-arm64": {
    triple: "aarch64-unknown-linux-musl",
    pkg: "@openai/codex-linux-arm64",
  },
  "darwin-x64": {
    triple: "x86_64-apple-darwin",
    pkg: "@openai/codex-darwin-x64",
  },
  "darwin-arm64": {
    triple: "aarch64-apple-darwin",
    pkg: "@openai/codex-darwin-arm64",
  },
  "win32-x64": {
    triple: "x86_64-pc-windows-msvc",
    pkg: "@openai/codex-win32-x64",
  },
  "win32-arm64": {
    triple: "aarch64-pc-windows-msvc",
    pkg: "@openai/codex-win32-arm64",
  },
};

/**
 * Resolve the native codex binary vendored by `@openai/codex`'s platform sub-package,
 * so the adapter works from a plain `npm install @posthog/agent` with no download.
 * Returns undefined when the dep or this platform's sub-package isn't installed.
 */
function vendoredCodexBinary(): string | undefined {
  const target = CODEX_NATIVE_TARGETS[`${process.platform}-${process.arch}`];
  if (!target) return undefined;
  const binaryName = process.platform === "win32" ? "codex.exe" : "codex";
  try {
    // Anchor resolution at this module's dir; the createRequire filename need not
    // exist (only its directory is used).
    const requireFrom = createRequire(
      join(import.meta.dirname ?? __dirname, "_resolve.js"),
    );
    const pkgJson = requireFrom.resolve(`${target.pkg}/package.json`);
    const binary = join(
      dirname(pkgJson),
      "vendor",
      target.triple,
      "bin",
      binaryName,
    );
    return existsSync(binary) ? binary : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Path to the native codex CLI (the one that exposes `app-server`), or undefined
 * when unavailable. Sources in order: the hint itself when it already points at
 * the codex binary, a `codex` sibling of the hint (older hosts pass another
 * bundled binary's path in the same directory), then the binary vendored by the
 * `@openai/codex` npm dependency.
 */
export function nativeCodexBinaryPath(
  bundledHintPath?: string,
): string | undefined {
  const binaryName = process.platform === "win32" ? "codex.exe" : "codex";
  if (bundledHintPath) {
    const candidate =
      basename(bundledHintPath) === binaryName
        ? bundledHintPath
        : join(dirname(bundledHintPath), binaryName);
    if (existsSync(candidate)) return candidate;
  }
  return vendoredCodexBinary();
}
