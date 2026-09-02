import { describe, expect, it, vi } from "vitest";
import {
  type DarwinMountEntry,
  isMacosAppTranslocationPath,
  isMacosPackagedUnsafeBundleLocation,
  isMacosPathOnReadOnlyNonRootMountFromTable,
  parseDarwinMountTable,
  type ReadDarwinMountTable,
} from "./macos-packaged-install-guard";

describe("isMacosAppTranslocationPath", () => {
  it.each([
    {
      case: "appPath is translocated",
      appPath:
        "/private/var/folders/yf/xx/AppTranslocation/C6283C3C-9D6E-4D81-A7D5-8BA2567ED486/d/PostHog.app/Contents/Resources/app.asar",
      exePath: "/Applications/PostHog.app/Contents/MacOS/PostHog",
      expected: true,
    },
    {
      case: "exePath is translocated",
      appPath: "/Applications/PostHog.app/Contents/Resources/app.asar",
      exePath:
        "/private/var/folders/yf/xx/AppTranslocation/C6283C3C/d/PostHog.app/Contents/MacOS/PostHog",
      expected: true,
    },
    {
      case: "neither path is translocated (/Applications)",
      appPath: "/Applications/PostHog.app/Contents/Resources/app.asar",
      exePath: "/Applications/PostHog.app/Contents/MacOS/PostHog",
      expected: false,
    },
    {
      case: "neither path is translocated (/Users)",
      appPath: "/Users/dev/PostHog.app/Contents/Resources/app.asar",
      exePath: "/Users/dev/PostHog.app/Contents/MacOS/PostHog",
      expected: false,
    },
  ])("$case → $expected", ({ appPath, exePath, expected }) => {
    expect(isMacosAppTranslocationPath(appPath, exePath)).toBe(expected);
  });
});

describe("parseDarwinMountTable", () => {
  it.each<{
    case: string;
    input: string;
    expected: DarwinMountEntry[];
  }>([
    {
      case: "standard macOS mount lines",
      input: `/dev/disk3s1s1 on / (apfs, sealed, local, read-only, journaled)
/dev/disk7s1 on /Volumes/My Dmg (apfs, local, read-only, journaled)
/dev/disk5s1 on /Volumes/Writable (apfs, local, journaled)
`,
      expected: [
        {
          mountPoint: "/",
          options: "apfs, sealed, local, read-only, journaled",
        },
        {
          mountPoint: "/Volumes/My Dmg",
          options: "apfs, local, read-only, journaled",
        },
        { mountPoint: "/Volumes/Writable", options: "apfs, local, journaled" },
      ],
    },
    {
      case: "mount point name contains ' (' — anchors to trailing options",
      input:
        "/dev/disk9s1 on /Volumes/My Backup (2) (apfs, local, read-only, journaled)\n",
      expected: [
        {
          mountPoint: "/Volumes/My Backup (2)",
          options: "apfs, local, read-only, journaled",
        },
      ],
    },
  ])("parses: $case", ({ input, expected }) => {
    expect(parseDarwinMountTable(input)).toEqual(expected);
  });
});

describe("isMacosPathOnReadOnlyNonRootMountFromTable", () => {
  const baseTable = `/dev/disk3s1s1 on / (apfs, sealed, local, read-only, journaled)
/dev/disk7s1 on /Volumes/ReadOnlyVol (apfs, local, read-only, journaled)
/dev/disk5s1 on /Volumes/Writable (apfs, local, journaled)
`;
  const nestedTable = `/dev/x on / (apfs, read-only)
/dev/y on /Volumes/RW (apfs, local, journaled)
/dev/z on /Volumes/RW/nested (apfs, local, read-only)
`;

  it.each([
    {
      case: "path under read-only / is ignored (Users)",
      table: baseTable,
      path: "/Users/me/app",
      expected: false,
    },
    {
      case: "path under read-only / is ignored (Applications)",
      table: baseTable,
      path: "/Applications/Foo.app",
      expected: false,
    },
    {
      case: "read-only non-root volume",
      table: baseTable,
      path: "/Volumes/ReadOnlyVol/PostHog.app/Contents/MacOS/PostHog",
      expected: true,
    },
    {
      case: "writable non-root volume",
      table: baseTable,
      path: "/Volumes/Writable/out/PostHog.app/Contents/MacOS/PostHog",
      expected: false,
    },
    {
      case: "nested read-only mount wins over writable parent",
      table: nestedTable,
      path: "/Volumes/RW/nested/app",
      expected: true,
    },
    {
      case: "writable parent wins when no deeper match",
      table: nestedTable,
      path: "/Volumes/RW/other/app",
      expected: false,
    },
  ])("$case → $expected", ({ table, path, expected }) => {
    expect(isMacosPathOnReadOnlyNonRootMountFromTable(path, table)).toBe(
      expected,
    );
  });
});

describe("isMacosPackagedUnsafeBundleLocation", () => {
  const writableMountTable = `/dev/disk3s1s1 on / (apfs, sealed, local, read-only, journaled)
/dev/disk5s1 on /Volumes/build (apfs, local, journaled)
/dev/disk6s1 on /Applications (apfs, local, journaled)
`;
  const readOnlyMountTable = `/dev/disk3s1s1 on / (apfs, sealed, local, read-only, journaled)
/dev/disk7s1 on /Volumes/ReadOnlyVol (apfs, local, read-only, journaled)
`;

  it.each<{
    case: string;
    appPath: string;
    exePath: string;
    readMountTable: ReadDarwinMountTable;
    expected: boolean;
  }>([
    {
      case: "translocated bundle",
      appPath:
        "/private/var/.../AppTranslocation/UUID/d/PostHog.app/Contents/Resources/app.asar",
      exePath: "/Applications/PostHog.app/Contents/MacOS/PostHog",
      readMountTable: () => writableMountTable,
      expected: true,
    },
    {
      case: "ordinary non-translocated path on a writable mount",
      appPath: "/Volumes/build/out/PostHog.app/Contents/Resources/app.asar",
      exePath: "/Volumes/build/out/PostHog.app/Contents/MacOS/PostHog",
      readMountTable: () => writableMountTable,
      expected: false,
    },
    {
      case: "bundle on a read-only non-root volume",
      appPath: "/Volumes/ReadOnlyVol/PostHog.app/Contents/Resources/app.asar",
      exePath: "/Volumes/ReadOnlyVol/PostHog.app/Contents/MacOS/PostHog",
      readMountTable: () => readOnlyMountTable,
      expected: true,
    },
    {
      case: "mount table cannot be read (degrade to non-blocking)",
      appPath: "/Applications/PostHog.app/Contents/Resources/app.asar",
      exePath: "/Applications/PostHog.app/Contents/MacOS/PostHog",
      readMountTable: () => null,
      expected: false,
    },
  ])("$case → $expected", ({ appPath, exePath, readMountTable, expected }) => {
    expect(
      isMacosPackagedUnsafeBundleLocation(appPath, exePath, readMountTable),
    ).toBe(expected);
  });

  it("short-circuits on translocation without reading the mount table", () => {
    const readMountTable = vi.fn(() => writableMountTable);
    isMacosPackagedUnsafeBundleLocation(
      "/private/var/.../AppTranslocation/UUID/d/PostHog.app/Contents/Resources/app.asar",
      "/Applications/PostHog.app/Contents/MacOS/PostHog",
      readMountTable,
    );
    expect(readMountTable).not.toHaveBeenCalled();
  });
});
