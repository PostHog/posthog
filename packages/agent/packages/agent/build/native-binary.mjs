import { join } from "node:path";

/**
 * Shared build-time helpers for resolving the Claude native binary that ships
 * via `@anthropic-ai/claude-agent-sdk-${platform}-${arch}` optional deps.
 *
 * Used by both `packages/agent/tsup.config.ts` (bundles the binary into the
 * agent package's `dist/claude-cli/`) and `apps/code/vite-main-plugins.mts`
 * (copies it into the Electron app's `.vite/build/claude-cli/`).
 *
 * The runtime equivalent of this lives upstream in `acp-agent.ts` as
 * `claudeCliPath()` + `isMuslLibc()`. Keep behavior in sync if the upstream
 * resolution logic changes.
 */

/** Cross-compile aware platform — electron-forge sets npm_config_platform when packaging for a target. */
export function targetPlatform() {
  return process.env.npm_config_platform ?? process.platform;
}

/** Cross-compile aware arch — same story as targetPlatform. */
export function targetArch() {
  return process.env.npm_config_arch ?? process.arch;
}

export function claudeBinName(platform = targetPlatform()) {
  return platform === "win32" ? "claude.exe" : "claude";
}

export const CLAUDE_CLI_SUPPORT_FILES = [
  "package.json",
  "manifest.json",
  "manifest.zst.json",
  "yoga.wasm",
];

export const CLAUDE_CLI_SUPPORT_DIRS = ["vendor"];

/**
 * Detect whether the *current* Node was built against musl libc (not glibc).
 * Only meaningful when targetPlatform() === "linux" and we're running on
 * linux — cross-host packaging defaults to glibc ordering since we have no
 * way to know the target's libc.
 */
export function isMuslLibc() {
  if (process.platform !== "linux") return false;
  const report = process.report?.getReport();
  const header = report?.header;
  return !header?.glibcVersionRuntime;
}

/**
 * Ordered list of candidate paths to a Claude native binary inside a given
 * node_modules root. First entry that exists should be preferred.
 */
export function nativeBinaryCandidates(rootNodeModules) {
  const platform = targetPlatform();
  const arch = targetArch();
  const binary = claudeBinName(platform);
  const slugs =
    platform === "linux"
      ? isMuslLibc()
        ? [`linux-${arch}-musl`, `linux-${arch}`]
        : [`linux-${arch}`, `linux-${arch}-musl`]
      : [`${platform}-${arch}`];
  return slugs.map((slug) =>
    join(rootNodeModules, `@anthropic-ai/claude-agent-sdk-${slug}`, binary),
  );
}

/**
 * SDK 0.3.x is in the middle of transitioning from a monolithic `cli.js`
 * package layout to platform-specific native executables. Keep the legacy
 * entrypoint as a fallback until the optional native packages are universally
 * available across our build environments.
 */
export function legacyCliCandidates(rootNodeModules) {
  return [join(rootNodeModules, "@anthropic-ai/claude-agent-sdk", "cli.js")];
}

export function claudeExecutableCandidates(rootNodeModules) {
  return [
    ...nativeBinaryCandidates(rootNodeModules),
    ...legacyCliCandidates(rootNodeModules),
  ];
}
