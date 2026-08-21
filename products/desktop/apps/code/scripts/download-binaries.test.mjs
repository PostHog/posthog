import { chmodSync, existsSync, renameSync } from "node:fs";
import { setTimeout as sleep } from "node:timers/promises";
import { extract } from "tar";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  BINARIES,
  downloadBinary,
  downloadFile,
  MAX_DOWNLOAD_ATTEMPTS,
} from "./download-binaries.mjs";

vi.mock("node:timers/promises", () => {
  const setTimeout = vi.fn(() => Promise.resolve());
  return { setTimeout, default: { setTimeout } };
});
vi.mock("node:stream/promises", () => {
  const pipeline = vi.fn(() => Promise.resolve());
  return { pipeline, default: { pipeline } };
});
vi.mock("tar", () => {
  const extract = vi.fn(() => Promise.resolve());
  return { extract, default: { extract } };
});
vi.mock("adm-zip", () => {
  const extractAllTo = vi.fn();
  return {
    default: class AdmZip {
      extractAllTo(...args) {
        extractAllTo(...args);
      }
    },
  };
});
vi.mock("node:fs", () => {
  const fns = {
    chmodSync: vi.fn(),
    createWriteStream: vi.fn(() => ({})),
    existsSync: vi.fn(() => true),
    mkdirSync: vi.fn(),
    realpathSync: vi.fn(() => "/not/the/entrypoint"),
    renameSync: vi.fn(),
    rmSync: vi.fn(),
  };
  return { ...fns, default: fns };
});

const okResponse = () => ({
  ok: true,
  status: 200,
  statusText: "OK",
  body: {},
});
const errorResponse = (status, statusText) => ({
  ok: false,
  status,
  statusText,
  body: null,
});

describe("download binaries", () => {
  let fetchMock;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  it("downloads on the first attempt without retrying", async () => {
    fetchMock.mockResolvedValue(okResponse());

    await downloadFile("https://example.test/bin.tar.gz", "/tmp/bin.tar.gz");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(sleep).not.toHaveBeenCalled();
  });

  it("retries retriable HTTP statuses then succeeds", async () => {
    fetchMock
      .mockResolvedValueOnce(errorResponse(503, "Service Unavailable"))
      .mockResolvedValueOnce(errorResponse(504, "Gateway Time-out"))
      .mockResolvedValueOnce(okResponse());

    await downloadFile("u", "/tmp/bin");

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(sleep).toHaveBeenCalledTimes(2);
  });

  it("fails fast on non-retriable HTTP statuses", async () => {
    fetchMock.mockResolvedValue(errorResponse(404, "Not Found"));

    await expect(downloadFile("u", "/tmp/bin")).rejects.toThrow("HTTP 404");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(sleep).not.toHaveBeenCalled();
  });

  it("retries network-level errors that carry no HTTP status", async () => {
    fetchMock
      .mockRejectedValueOnce(new Error("ECONNRESET"))
      .mockRejectedValueOnce(new TypeError("fetch failed"))
      .mockResolvedValueOnce(okResponse());

    await downloadFile("u", "/tmp/bin");

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(sleep).toHaveBeenCalledTimes(2);
  });

  it("gives up after MAX_DOWNLOAD_ATTEMPTS and rethrows the last error", async () => {
    fetchMock.mockResolvedValue(errorResponse(503, "Service Unavailable"));

    await expect(downloadFile("u", "/tmp/bin")).rejects.toThrow("HTTP 503");
    expect(fetchMock).toHaveBeenCalledTimes(MAX_DOWNLOAD_ATTEMPTS);
    expect(sleep).toHaveBeenCalledTimes(MAX_DOWNLOAD_ATTEMPTS - 1);
  });

  it("backs off exponentially with jitter inside the expected bounds", async () => {
    fetchMock.mockResolvedValue(errorResponse(503, "Service Unavailable"));

    await expect(downloadFile("u", "/tmp/bin")).rejects.toThrow();

    const delays = sleep.mock.calls.map(([ms]) => ms);
    expect(delays).toHaveLength(MAX_DOWNLOAD_ATTEMPTS - 1);
    delays.forEach((delay, i) => {
      const base = Math.min(1000 * 2 ** i, 15000);
      expect(delay).toBeGreaterThanOrEqual(base * 0.5);
      expect(delay).toBeLessThan(base);
    });
  });

  it("downloads and stages the codex code-mode host beside codex", async () => {
    const hostBinary = BINARIES.find(
      (binary) => binary.name === "codex-code-mode-host",
    );
    expect(hostBinary).toBeDefined();

    const destination = "/tmp/codex-binaries";
    const target = hostBinary.getTarget();
    const extractedPath = `${destination}/${hostBinary.archiveBinaryName(target)}`;
    const binaryName =
      process.platform === "win32"
        ? "codex-code-mode-host.exe"
        : "codex-code-mode-host";
    const binaryPath = `${destination}/${binaryName}`;
    const archiveSuffix = target.includes("windows") ? ".exe.zip" : ".tar.gz";
    const archiveExtension = target.includes("windows") ? ".zip" : ".tar.gz";
    const files = new Set([extractedPath]);

    existsSync.mockImplementation((path) => files.has(path));
    renameSync.mockImplementation((source, targetPath) => {
      files.delete(source);
      files.add(targetPath);
    });
    fetchMock.mockResolvedValue(okResponse());

    await downloadBinary(hostBinary, destination);

    expect(fetchMock).toHaveBeenCalledWith(
      `https://github.com/openai/codex/releases/download/rust-v${hostBinary.version}/codex-code-mode-host-${target}${archiveSuffix}`,
      { redirect: "follow" },
    );
    if (process.platform !== "win32") {
      expect(extract).toHaveBeenCalledWith({
        file: `${destination}/codex-code-mode-host-archive${archiveExtension}`,
        cwd: destination,
      });
    }
    expect(renameSync).toHaveBeenCalledWith(extractedPath, binaryPath);
    expect(chmodSync).toHaveBeenCalledWith(binaryPath, 0o755);
  });

  it.each([
    ["aarch64-apple-darwin", "codex-code-mode-host-aarch64-apple-darwin"],
    [
      "x86_64-pc-windows-msvc",
      "codex-code-mode-host-x86_64-pc-windows-msvc.exe",
    ],
  ])("uses the upstream host archive member for %s", (target, expected) => {
    const hostBinary = BINARIES.find(
      (binary) => binary.name === "codex-code-mode-host",
    );

    expect(hostBinary?.archiveBinaryName(target)).toBe(expected);
  });
});
