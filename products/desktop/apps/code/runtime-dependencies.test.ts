import micromatch from "micromatch";
import { describe, expect, it } from "vitest";
import {
  asarUnpackGlobs,
  buildExternals,
  koffiPackageFor,
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

describe("koffiPackageFor", () => {
  it.each([
    ["mac", 1, "@koromix/koffi-darwin-x64"],
    ["mac", 3, "@koromix/koffi-darwin-arm64"],
  ])("maps platform=%s arch=%i to %s", (platform, arch, expected) => {
    expect(koffiPackageFor(platform, arch as number)).toBe(expected);
  });

  it.each([
    ["windows", 1],
    ["linux", 3],
    ["darwin", 3],
  ])(
    "returns null for platform=%s, which never stages koffi",
    (platform, arch) => {
      // koffi only reads the macOS window list, and electron-builder names that
      // platform "mac" — "darwin" is the same mistake that once left the Windows
      // watcher binary unstaged.
      expect(koffiPackageFor(platform, arch as number)).toBeNull();
    },
  );
});

/**
 * Arch-specific packages are named by watcherPackageFor / koffiPackageFor rather
 * than by any list, so nothing gives them a glob automatically. electron-builder
 * drops all of node_modules and re-includes only these globs, so a scope nobody
 * covers is stripped and its prebuilt binary never reaches the app — and the only
 * symptom is the feature failing in a packaged build. @koromix shipped that way.
 */
describe("staged arch-specific binaries reach the packaged app", () => {
  it.each([
    ["@parcel/watcher-darwin-arm64", "watcher.node"],
    ["@parcel/watcher-linux-x64-glibc", "watcher.node"],
    ["@parcel/watcher-win32-x64", "watcher.node"],
    ["@koromix/koffi-darwin-arm64", "darwin_arm64/koffi.node"],
    ["@koromix/koffi-darwin-x64", "darwin_x64/koffi.node"],
  ])("packages and unpacks %s", (pkg, binary) => {
    const path = `node_modules/${pkg}/${binary}`;

    expect(micromatch.isMatch(path, packagedFileGlobs)).toBe(true);
    // A .node inside the asar cannot be dlopened, so being packaged is only half
    // of reaching the app.
    expect(micromatch.isMatch(path, asarUnpackGlobs)).toBe(true);
  });

  it("covers every package the stagers can name", () => {
    const staged = [
      ...["mac", "windows", "linux"].flatMap((platform) =>
        [1, 3].map((arch) => watcherPackageFor(platform, arch)),
      ),
      ...["mac", "windows", "linux"].flatMap((platform) =>
        [1, 3].map((arch) => koffiPackageFor(platform, arch)),
      ),
    ].filter((pkg): pkg is string => pkg !== null);

    for (const pkg of staged) {
      expect(
        micromatch.isMatch(
          `node_modules/${pkg}/package.json`,
          packagedFileGlobs,
        ),
      ).toBe(true);
    }
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
