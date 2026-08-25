/**
 * Makes pi itself answer to "hog" instead of "pi": `--help`/usage text, the
 * default startup banner, slash-command descriptions, generated env var
 * names (`HOG_CODING_AGENT_DIR` instead of `PI_CODING_AGENT_DIR`), and
 * error messages all derive from `@earendil-works/pi-coding-agent`'s
 * `APP_NAME`/`APP_TITLE`/`CONFIG_DIR_NAME` constants (see its
 * `config.js`), which are themselves read from a `piConfig: { name,
 * configDir }` field on *the nearest `package.json` pi finds walking up
 * from its own `dist/` directory* — i.e. pi's own vendored `package.json`,
 * which we must not hand-edit (it's overwritten on every reinstall/version
 * bump).
 *
 * pi supports overriding that lookup directory with `PI_PACKAGE_DIR`
 * ("useful for Nix/Guix where store paths tokenize poorly" per its own
 * comment) — checked *before* its compiled-binary-specific
 * `dirname(process.execPath)` fallback, so setting it works for the
 * in-process CLI, the SDK, subprocess spawns, and (when resolution
 * succeeds — see the compiled-binary caveat below) the standalone binary
 * alike.
 *
 * This module materializes a small directory containing a `package.json`
 * with `piConfig: { name: "hog" }`, symlinks *every other entry* of the
 * real pi package root into it (`dist/`, `docs/`, `examples/`,
 * `README.md`, …) — `getPackageDir()` isn't only used for docs/README/
 * examples paths; pi also loads runtime assets relative to it (e.g.
 * built-in theme JSON under `dist/modes/interactive/theme/`), so anything
 * short of mirroring the whole package root risks an `ENOENT` the moment
 * pi reaches for one of those — and copies over `name`/`version` so
 * `PACKAGE_NAME` (used for self-update checks) and `VERSION` (shown in the
 * startup header) stay accurate.
 *
 * `installHogBrandEnv()` must be *called* (not just imported — see below)
 * before `@earendil-works/pi-coding-agent` is evaluated, because
 * `APP_NAME`/`APP_TITLE`/`CONFIG_DIR_NAME` are read from `PI_PACKAGE_DIR` at
 * module-evaluation time, not lazily. `cli.ts`, `bin/hog.ts`, and
 * `runtime.ts` call it before dynamically importing
 * `@earendil-works/pi-coding-agent` or any local module that transitively
 * imports the SDK.
 *
 * That dynamic-import requirement is not optional styling: once bundled,
 * a static `import "./brand-env"` followed by a static
 * `import { main } from "@earendil-works/pi-coding-agent"` does *not*
 * guarantee ordering. ES module semantics evaluate a module's *own*
 * dependencies (all of them, regardless of textual position) before any of
 * that module's own top-level statements run — and bundling can merge
 * originally-separate files into one output module, collapsing the file
 * boundary that ordering relied on. A real `await import(...)`, by
 * contrast, is never hoisted ahead of preceding synchronous statements, so
 * it reliably runs after `installHogBrandEnv()` regardless of bundling.
 *
 * The subagent's `pi-subprocess.ts` uses `withHogBrandEnv()` when it spawns
 * Pi subprocesses — no ordering concerns there, since it only builds a
 * plain environment object for a child process.
 *
 * Deliberately keeps `configDir: ".pi"` (not `.hog`) so existing pi
 * credentials, sessions, and MCP auth on disk keep working unchanged for
 * anyone who has both installed.
 *
 * Best-effort: inside the standalone `bun build --compile` binary (see
 * `bin/hog.ts`) there is no real `node_modules` tree to resolve
 * `@earendil-works/pi-coding-agent`'s package root against — the same
 * limitation that excludes the `subagent` extension from that binary — so
 * failures here are swallowed and Pi falls back to its
 * own "pi"/"π" naming rather than crashing startup.
 */
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const HOG_APP_NAME = "hog";
export const HOG_BRAND_TAGLINE = "A Pi distribution by PostHog";
// Keep pi's own on-disk config dir name so existing pi credentials,
// sessions, and MCP auth continue to work unchanged.
export const HOG_CONFIG_DIR_NAME = ".pi";

// Undefined = not attempted yet; null = attempted and failed (fall back to
// pi's own naming); string = ready to use.
let cachedManifestDir: string | null | undefined;

interface RealPackageInfo {
  root: string;
  name: string;
  version: string;
}

function resolveRealPiPackage(): RealPackageInfo {
  const entryFile = fileURLToPath(
    import.meta.resolve("@earendil-works/pi-coding-agent"),
  );
  // entryFile is `.../pi-coding-agent/dist/index.js`; the package root
  // (with package.json, docs/, examples/, README.md) is two levels up.
  const root = dirname(dirname(entryFile));
  const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf-8"));
  return {
    root,
    name: pkg.name ?? "@earendil-works/pi-coding-agent",
    version: pkg.version ?? "0.0.0",
  };
}

function linkIfMissing(target: string, linkPath: string): void {
  if (!existsSync(target) || existsSync(linkPath)) return;
  const type = lstatSync(target).isDirectory() ? "dir" : "file";
  symlinkSync(target, linkPath, type);
}

/**
 * Builds (or reuses) the manifest directory pi should read its branding
 * from, and returns its path — or `null` if it couldn't be prepared (e.g.
 * inside the compiled binary, where `@earendil-works/pi-coding-agent`
 * can't be resolved against a real `node_modules` tree).
 */
export function hogBrandManifestDir(): string | null {
  if (cachedManifestDir !== undefined) return cachedManifestDir;
  try {
    const real = resolveRealPiPackage();
    const manifestDir = join(tmpdir(), "posthog-hog-brand");
    mkdirSync(manifestDir, { recursive: true });
    writeFileSync(
      join(manifestDir, "package.json"),
      `${JSON.stringify(
        {
          name: real.name,
          version: real.version,
          piConfig: { name: HOG_APP_NAME, configDir: HOG_CONFIG_DIR_NAME },
        },
        null,
        2,
      )}\n`,
    );
    for (const entry of readdirSync(real.root)) {
      if (entry === "package.json") continue;
      linkIfMissing(join(real.root, entry), join(manifestDir, entry));
    }
    cachedManifestDir = manifestDir;
  } catch {
    cachedManifestDir = null;
  }
  return cachedManifestDir;
}

/**
 * Merges `PI_PACKAGE_DIR` into `env` for spawning a Pi subprocess, unless the
 * caller already set one or the manifest directory couldn't be prepared.
 */
export function withHogBrandEnv(
  env: NodeJS.ProcessEnv = process.env,
): NodeJS.ProcessEnv {
  if (env.PI_PACKAGE_DIR) return env;
  const dir = hogBrandManifestDir();
  return dir ? { ...env, PI_PACKAGE_DIR: dir } : env;
}

/**
 * Side effect: sets `process.env.PI_PACKAGE_DIR` for the current process,
 * in place, so that pi's config module — imported right after this one —
 * picks up "hog" branding when it first evaluates.
 */
export function installHogBrandEnv(): void {
  if (process.env.PI_PACKAGE_DIR) return;
  const dir = hogBrandManifestDir();
  if (dir) process.env.PI_PACKAGE_DIR = dir;
}

/**
 * One-line brand banner (`hog (A Pi distribution by PostHog) vX.Y.Z`),
 * matching the TUI header's `brandLine()` in `./extension.ts` but as plain
 * text — for non-interactive surfaces like `--help` output, which pi
 * generates itself (see `cli/args.js`'s `printHelp()`) and only rebrands
 * as far as `APP_NAME`/`APP_TITLE` go, with no tagline of its own.
 */
export function formatHogBrandBanner(version: string): string {
  return `${HOG_APP_NAME} (${HOG_BRAND_TAGLINE}) v${version}`;
}

/** Whether `argv` (e.g. `process.argv.slice(2)`) requests pi's own
 * `--help`/`-h` usage text, which `cli.ts`/`bin/hog.ts` prefix with
 * `formatHogBrandBanner()` before delegating to pi's `main()`. */
export function isHelpRequest(argv: string[]): boolean {
  return argv.includes("--help") || argv.includes("-h");
}
