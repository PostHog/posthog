import { describe, expect, it, vi } from "vitest";

const execFile = vi.hoisted(() => vi.fn());
const existsSync = vi.hoisted(() => vi.fn());

vi.mock("node:child_process", () => ({
  default: { execFile },
  execFile,
}));
vi.mock("node:fs", () => ({ default: { existsSync }, existsSync }));
vi.mock("node:util", () => ({
  default: { promisify: () => execFile },
  promisify: () => execFile,
}));
vi.mock("electron", () => ({ shell: { openExternal: vi.fn() } }));

import { ElectronUrlLauncher } from "./electron-url-launcher";

function overridePlatform(value: NodeJS.Platform): () => void {
  const platform = Object.getOwnPropertyDescriptor(process, "platform");
  if (!platform) throw new Error("process.platform descriptor is missing");

  Object.defineProperty(process, "platform", { value });
  return () => Object.defineProperty(process, "platform", platform);
}

describe("ElectronUrlLauncher", () => {
  it("opens Chrome remote debugging in Google Chrome on macOS", async () => {
    const restorePlatform = overridePlatform("darwin");
    execFile.mockResolvedValue(undefined);

    try {
      await new ElectronUrlLauncher().launchChromeRemoteDebugging();
    } finally {
      restorePlatform();
    }

    expect(execFile).toHaveBeenCalledWith("open", [
      "-a",
      "Google Chrome",
      "chrome://inspect/#remote-debugging",
    ]);
  });

  it("opens Chrome remote debugging in a Windows Chrome installation", async () => {
    const programFiles = process.env.ProgramFiles;
    const restorePlatform = overridePlatform("win32");
    process.env.ProgramFiles = "C:\\Program Files";
    existsSync.mockImplementation(
      (filePath) =>
        filePath === "C:\\Program Files/Google/Chrome/Application/chrome.exe",
    );
    execFile.mockResolvedValue(undefined);

    try {
      await new ElectronUrlLauncher().launchChromeRemoteDebugging();
    } finally {
      restorePlatform();
      process.env.ProgramFiles = programFiles;
    }

    expect(execFile).toHaveBeenCalledWith(
      "C:\\Program Files/Google/Chrome/Application/chrome.exe",
      ["chrome://inspect/#remote-debugging"],
    );
  });
});
