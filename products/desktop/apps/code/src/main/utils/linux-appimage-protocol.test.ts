import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./logger", () => ({
  logger: {
    scope: () => ({
      info: vi.fn(),
      error: vi.fn(),
      warn: vi.fn(),
      debug: vi.fn(),
    }),
  },
}));

const fsMocks = vi.hoisted(() => ({
  mkdirSync: vi.fn(),
  writeFileSync: vi.fn(),
  copyFileSync: vi.fn(),
  existsSync: vi.fn(() => false),
}));

vi.mock("node:fs", () => ({ default: fsMocks, ...fsMocks }));

const execFileMock = vi.hoisted(() => vi.fn());
vi.mock("node:child_process", () => ({
  default: { execFile: execFileMock },
  execFile: execFileMock,
}));

import {
  buildAppImageDesktopEntry,
  isAppImage,
  registerAppImageSchemes,
} from "./linux-appimage-protocol";

const originalPlatform = process.platform;
const originalAppImage = process.env.APPIMAGE;
const originalAppDir = process.env.APPDIR;

function setPlatform(platform: NodeJS.Platform): void {
  Object.defineProperty(process, "platform", {
    value: platform,
    configurable: true,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  fsMocks.existsSync.mockReturnValue(false);
  // execFile(cmd, args, cb) — invoke the callback with no error by default.
  execFileMock.mockImplementation(
    (_cmd: string, _args: string[], cb: (err: Error | null) => void) => {
      cb(null);
    },
  );
});

afterEach(() => {
  setPlatform(originalPlatform);
  if (originalAppImage === undefined) delete process.env.APPIMAGE;
  else process.env.APPIMAGE = originalAppImage;
  if (originalAppDir === undefined) delete process.env.APPDIR;
  else process.env.APPDIR = originalAppDir;
});

describe("isAppImage", () => {
  it.each([
    {
      name: "is true on linux with APPIMAGE set",
      platform: "linux" as const,
      appImage: "/home/u/Apps/posthog_code.appimage",
      expected: true,
    },
    {
      name: "is false when APPIMAGE is not set",
      platform: "linux" as const,
      appImage: undefined,
      expected: false,
    },
    {
      name: "is false on non-linux platforms even with APPIMAGE set",
      platform: "darwin" as const,
      appImage: "/whatever",
      expected: false,
    },
  ])("$name", ({ platform, appImage, expected }) => {
    setPlatform(platform);
    if (appImage === undefined) delete process.env.APPIMAGE;
    else process.env.APPIMAGE = appImage;
    expect(isAppImage()).toBe(expected);
  });
});

describe("buildAppImageDesktopEntry", () => {
  it("points Exec at the stable APPIMAGE path and lists every scheme", () => {
    const entry = buildAppImageDesktopEntry({
      appImagePath: "/home/u/Apps/posthog_code.appimage",
      schemes: ["posthog-code", "twig", "array"],
    });

    expect(entry).toContain('Exec="/home/u/Apps/posthog_code.appimage" %U');
    expect(entry).toContain(
      "MimeType=x-scheme-handler/posthog-code;x-scheme-handler/twig;x-scheme-handler/array;",
    );
    expect(entry).toContain("Name=PostHog");
    expect(entry.startsWith("[Desktop Entry]")).toBe(true);
  });

  it("uses an absolute icon path when one is staged", () => {
    const entry = buildAppImageDesktopEntry({
      appImagePath: "/a.appimage",
      schemes: ["posthog-code"],
      iconPath: "/home/u/.local/share/icons/posthog-code.png",
    });
    expect(entry).toContain("Icon=/home/u/.local/share/icons/posthog-code.png");
  });
});

describe("registerAppImageSchemes", () => {
  it("writes the desktop entry and registers each scheme as default", async () => {
    process.env.APPIMAGE = "/home/u/Apps/posthog_code.appimage";

    await registerAppImageSchemes(["posthog-code", "twig"]);

    expect(fsMocks.writeFileSync).toHaveBeenCalledTimes(1);
    const [writtenPath, contents] = fsMocks.writeFileSync.mock.calls[0];
    expect(String(writtenPath)).toContain(
      ".local/share/applications/posthog-code.desktop",
    );
    expect(String(contents)).toContain(
      'Exec="/home/u/Apps/posthog_code.appimage" %U',
    );

    expect(execFileMock).toHaveBeenCalledWith(
      "update-desktop-database",
      expect.arrayContaining([expect.stringContaining("applications")]),
      expect.any(Function),
    );
    expect(execFileMock).toHaveBeenCalledWith(
      "xdg-mime",
      ["default", "posthog-code.desktop", "x-scheme-handler/posthog-code"],
      expect.any(Function),
    );
    expect(execFileMock).toHaveBeenCalledWith(
      "xdg-mime",
      ["default", "posthog-code.desktop", "x-scheme-handler/twig"],
      expect.any(Function),
    );
  });

  it("does nothing when not running as an AppImage", async () => {
    delete process.env.APPIMAGE;

    await registerAppImageSchemes(["posthog-code"]);

    expect(fsMocks.writeFileSync).not.toHaveBeenCalled();
    expect(execFileMock).not.toHaveBeenCalled();
  });
});
