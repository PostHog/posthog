// Single source of truth for native modules (and their runtime-required
// transitive deps). pnpm hoists these to the root node_modules; the packaged
// app needs real copies next to the bundle.
//
//   - scripts/before-pack.ts stages them from the hoisted root into the app's
//     local node_modules before electron-builder collects files.
//   - electron-builder.ts re-includes them (`files`) and unpacks the
//     binary-bearing ones from the asar (`asarUnpack`).
//   - electron.vite.config.ts marks the native ones external so Vite leaves
//     them to be resolved from node_modules at runtime.

// Staged + packaged on every platform.
export const runtimeNativeModules = [
  "node-pty",
  "node-addon-api",
  "@parcel/watcher",
  "better-sqlite3",
  "bindings",
  "file-uri-to-path",
  "prebuild-install",
  "micromatch",
  "is-glob",
  "detect-libc",
  "braces",
  "picomatch",
  "is-extglob",
  "fill-range",
  "to-regex-range",
  "is-number",
];

// The base native modules that must exist when packaging; a missing one is a
// broken build, not a warning. before-pack stages these with copyRequiredDep.
export const requiredNativeModules = [
  "node-pty",
  "@parcel/watcher",
  "better-sqlite3",
];

// file-icon is only used on macOS.
export const macOnlyNativeModules = ["file-icon"];

// The subset that ships compiled .node binaries and must be unpacked from asar.
const asarUnpackModules = [
  "node-pty",
  "@parcel/watcher",
  "file-icon",
  "better-sqlite3",
  "bindings",
  "file-uri-to-path",
];

// Modules Vite must not bundle (resolved from the staged node_modules at runtime).
export const buildExternals = [
  "node-pty",
  "@parcel/watcher",
  "file-icon",
  "better-sqlite3",
];

// electron-builder ships the whole @parcel scope so the platform-specific
// @parcel/watcher-<plat>-<arch> staged by before-pack is covered too.
const scopeOf = (name: string) =>
  name.startsWith("@parcel/") ? "@parcel" : name;

export const packagedFileGlobs = [
  ...runtimeNativeModules,
  ...macOnlyNativeModules,
].map((name) => `node_modules/${scopeOf(name)}/**/*`);

export const asarUnpackGlobs = asarUnpackModules.map(
  (name) => `node_modules/${scopeOf(name)}/**`,
);

// Mirrors electron-builder's Arch enum (ia32=0, x64=1, armv7l=2, arm64=3).
const ARCH_X64 = 1;
const ARCH_ARM64 = 3;

// The platform-specific @parcel/watcher prebuild before-pack must stage, keyed
// by electron-builder's platform name and arch. The name is "windows", not
// "win" (electron-builder's Platform.WINDOWS.name); matching "win" silently
// skips staging and ships a broken Windows app. Returns null for an
// unrecognized platform.
export function watcherPackageFor(
  platformName: string,
  arch: number,
): string | null {
  if (platformName === "mac") {
    return arch === ARCH_X64
      ? "@parcel/watcher-darwin-x64"
      : "@parcel/watcher-darwin-arm64";
  }
  if (platformName === "windows") {
    return arch === ARCH_ARM64
      ? "@parcel/watcher-win32-arm64"
      : "@parcel/watcher-win32-x64";
  }
  if (platformName === "linux") {
    return arch === ARCH_ARM64
      ? "@parcel/watcher-linux-arm64-glibc"
      : "@parcel/watcher-linux-x64-glibc";
  }
  return null;
}
