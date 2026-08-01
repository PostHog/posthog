import { describe, expect, it } from "vitest";
import {
  asarUnpackGlobs,
  buildExternals,
  macOnlyNativeModules,
  packagedFileGlobs,
  requiredNativeModules,
  runtimeNativeModules,
  watcherPackageFor,
} from "./runtime-dependencies";

describe("watcherPackageFor", () => {
  it.each([
    ["mac", 1, "@parcel/watcher-darwin-x64"],
    ["mac", 3, "@parcel/watcher-darwin-arm64"],
    ["windows", 1, "@parcel/watcher-win32-x64"],
    ["windows", 3, "@parcel/watcher-win32-arm64"],
    ["linux", 1, "@parcel/watcher-linux-x64-glibc"],
    ["linux", 3, "@parcel/watcher-linux-arm64-glibc"],
  ])("maps platform=%s arch=%i to %s", (platform, arch, expected) => {
    expect(watcherPackageFor(platform, arch as number)).toBe(expected);
  });

  it("returns null for an unrecognized platform name", () => {
    // electron-builder passes "windows", never "win"; matching "win" was the
    // bug that left the Windows watcher binary unstaged.
    expect(watcherPackageFor("win", 1)).toBeNull();
    expect(watcherPackageFor("darwin", 1)).toBeNull();
  });
});

describe("native module globs", () => {
  it("collapses the @parcel scope to a single glob", () => {
    expect(packagedFileGlobs).toContain("node_modules/@parcel/**/*");
    expect(asarUnpackGlobs).toContain("node_modules/@parcel/**");
    expect(packagedFileGlobs).not.toContain(
      "node_modules/@parcel/watcher/**/*",
    );
  });

  it("emits a per-package glob for unscoped modules", () => {
    expect(packagedFileGlobs).toContain("node_modules/node-pty/**/*");
    expect(packagedFileGlobs).toContain("node_modules/better-sqlite3/**/*");
  });
});

describe("native module list invariants", () => {
  it("only marks modules that are actually staged as required", () => {
    for (const mod of requiredNativeModules) {
      expect(runtimeNativeModules).toContain(mod);
    }
  });

  it("externalizes only modules staged on some platform", () => {
    const staged = new Set([...runtimeNativeModules, ...macOnlyNativeModules]);
    for (const mod of buildExternals) {
      expect(staged.has(mod)).toBe(true);
    }
  });
});
