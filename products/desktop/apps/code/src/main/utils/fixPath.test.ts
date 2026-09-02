import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockSpawnSync = vi.hoisted(() => vi.fn());
const mockExistsSync = vi.hoisted(() => vi.fn(() => false));
const mockReadFileSync = vi.hoisted(() => vi.fn());
const mockWriteFileSync = vi.hoisted(() => vi.fn());
const mockMkdirSync = vi.hoisted(() => vi.fn());
const mockUserInfo = vi.hoisted(() =>
  vi.fn(() => ({ shell: "/bin/zsh" }) as { shell: string | null }),
);
const mockGetUserDataDir = vi.hoisted(() => vi.fn(() => "/tmp/posthog-code"));

vi.mock("node:child_process", () => ({
  spawnSync: mockSpawnSync,
  default: { spawnSync: mockSpawnSync },
}));

vi.mock("node:fs", () => ({
  existsSync: mockExistsSync,
  readFileSync: mockReadFileSync,
  writeFileSync: mockWriteFileSync,
  mkdirSync: mockMkdirSync,
  default: {
    existsSync: mockExistsSync,
    readFileSync: mockReadFileSync,
    writeFileSync: mockWriteFileSync,
    mkdirSync: mockMkdirSync,
  },
}));

vi.mock("node:os", () => ({
  userInfo: mockUserInfo,
  default: { userInfo: mockUserInfo },
}));

vi.mock("./env", () => ({
  getUserDataDir: mockGetUserDataDir,
}));

const DELIMITER = "_SHELL_ENV_DELIMITER_";

function shellOutput(envPath: string): string {
  return `${DELIMITER}\nPATH=${envPath}\n${DELIMITER}`;
}

const ORIGINAL_PLATFORM = process.platform;
const ORIGINAL_PATH = process.env.PATH;

function setPlatform(platform: NodeJS.Platform) {
  Object.defineProperty(process, "platform", {
    value: platform,
    configurable: true,
  });
}

describe("fixPath", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.resetModules();
    setPlatform("darwin");
    process.env.PATH = "/usr/bin:/bin";
    mockExistsSync.mockReturnValue(false);
  });

  afterEach(() => {
    setPlatform(ORIGINAL_PLATFORM);
    process.env.PATH = ORIGINAL_PATH;
  });

  it("merges fallback paths when shell PATH lacks /opt/homebrew/bin", async () => {
    mockSpawnSync.mockReturnValue({
      status: 0,
      stdout: shellOutput("/usr/local/bin:/usr/bin:/bin"),
    });

    const { fixPath } = await import("./fixPath");
    fixPath();

    const parts = process.env.PATH?.split(":") ?? [];
    expect(parts).toContain("/opt/homebrew/bin");
    expect(parts).toContain("/opt/homebrew/sbin");
    expect(parts).toContain("/usr/local/bin");
    expect(parts).toContain("/usr/bin");
  });

  it("does not duplicate fallback paths already present in shell PATH", async () => {
    mockSpawnSync.mockReturnValue({
      status: 0,
      stdout: shellOutput("/opt/homebrew/bin:/usr/local/bin:/usr/bin"),
    });

    const { fixPath } = await import("./fixPath");
    fixPath();

    const parts = process.env.PATH?.split(":") ?? [];
    const homebrewCount = parts.filter((p) => p === "/opt/homebrew/bin").length;
    expect(homebrewCount).toBe(1);
    const usrLocalCount = parts.filter((p) => p === "/usr/local/bin").length;
    expect(usrLocalCount).toBe(1);
  });

  it("falls back to fallback paths when shell resolution fails entirely", async () => {
    mockSpawnSync.mockReturnValue({ status: 1, stdout: "" });

    const { fixPath } = await import("./fixPath");
    fixPath();

    const parts = process.env.PATH?.split(":") ?? [];
    expect(parts).toContain("/opt/homebrew/bin");
    expect(parts).toContain("/opt/homebrew/sbin");
    expect(parts).toContain("/usr/local/bin");
    expect(parts).toContain("/usr/bin");
  });

  it("merges fallback paths into a cached PATH that lacks them", async () => {
    mockExistsSync.mockReturnValue(true);
    mockReadFileSync.mockReturnValue(
      JSON.stringify({
        path: "/usr/local/bin:/usr/bin:/bin",
        timestamp: Date.now(),
      }),
    );

    const { fixPath } = await import("./fixPath");
    fixPath();

    const parts = process.env.PATH?.split(":") ?? [];
    expect(parts).toContain("/opt/homebrew/bin");
    expect(mockSpawnSync).not.toHaveBeenCalled();
  });

  it("ignores stale cache and re-resolves via shell", async () => {
    mockExistsSync.mockReturnValue(true);
    mockReadFileSync.mockReturnValue(
      JSON.stringify({
        path: "/some/old/path",
        timestamp: Date.now() - 2 * 60 * 60 * 1000,
      }),
    );
    mockSpawnSync.mockReturnValue({
      status: 0,
      stdout: shellOutput("/usr/local/bin:/usr/bin"),
    });

    const { fixPath } = await import("./fixPath");
    fixPath();

    expect(mockSpawnSync).toHaveBeenCalled();
    const parts = process.env.PATH?.split(":") ?? [];
    expect(parts).not.toContain("/some/old/path");
    expect(parts).toContain("/opt/homebrew/bin");
  });

  it("preserves entries from the inherited PATH that the login shell lacks", async () => {
    // Simulate launching from a terminal where .zshrc has added nvm/mise
    // paths that the -lc resolution (only sources .zprofile) won't see.
    process.env.PATH =
      "/Users/me/.nvm/versions/node/v22.0.0/bin:/Users/me/.local/share/pnpm:/usr/bin:/bin";
    mockSpawnSync.mockReturnValue({
      status: 0,
      stdout: shellOutput("/opt/homebrew/bin:/usr/bin:/bin"),
    });

    const { fixPath } = await import("./fixPath");
    fixPath();

    const parts = process.env.PATH?.split(":") ?? [];
    // Inherited entries (added by .zshrc, missing from .zprofile) survive.
    expect(parts).toContain("/Users/me/.nvm/versions/node/v22.0.0/bin");
    expect(parts).toContain("/Users/me/.local/share/pnpm");
    // Shell-resolved entries are still merged in.
    expect(parts).toContain("/opt/homebrew/bin");
  });

  it("preserves inherited PATH entries when reading from the cache", async () => {
    process.env.PATH = "/Users/me/.nvm/versions/node/v22.0.0/bin:/usr/bin:/bin";
    mockExistsSync.mockReturnValue(true);
    mockReadFileSync.mockReturnValue(
      JSON.stringify({
        path: "/opt/homebrew/bin:/usr/bin:/bin",
        timestamp: Date.now(),
      }),
    );

    const { fixPath } = await import("./fixPath");
    fixPath();

    const parts = process.env.PATH?.split(":") ?? [];
    expect(parts).toContain("/Users/me/.nvm/versions/node/v22.0.0/bin");
    expect(parts).toContain("/opt/homebrew/bin");
    expect(mockSpawnSync).not.toHaveBeenCalled();
  });

  it("returns early on win32 without touching PATH", async () => {
    setPlatform("win32");
    process.env.PATH = "C:\\Windows\\System32";

    const { fixPath } = await import("./fixPath");
    fixPath();

    expect(mockSpawnSync).not.toHaveBeenCalled();
    expect(process.env.PATH).toBe("C:\\Windows\\System32");
  });
});
