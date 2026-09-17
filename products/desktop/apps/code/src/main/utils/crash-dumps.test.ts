import {
  mkdirSync,
  mkdtempSync,
  readdirSync,
  utimesSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listCrashDumps, reportCrashDumps } from "./crash-dumps";

const warn = vi.hoisted(() => vi.fn());
vi.mock("./logger", () => ({
  logger: {
    scope: () => ({
      info: vi.fn(),
      error: vi.fn(),
      warn,
      debug: vi.fn(),
    }),
  },
}));

describe("crash dumps", () => {
  let crashDumpsDir: string;

  function writeDump(
    reportDir: string,
    fileName: string,
    ageSeconds: number,
  ): string {
    const dirPath = path.join(crashDumpsDir, reportDir);
    mkdirSync(dirPath, { recursive: true });
    const filePath = path.join(dirPath, fileName);
    writeFileSync(filePath, "minidump");
    const seconds = Date.now() / 1000 - ageSeconds;
    utimesSync(filePath, seconds, seconds);
    return filePath;
  }

  beforeEach(() => {
    crashDumpsDir = mkdtempSync(path.join(tmpdir(), "crash-dumps-"));
    warn.mockClear();
  });

  it.each([
    ["a missing directory", () => path.join(crashDumpsDir, "absent")],
    ["a directory with no reports", () => crashDumpsDir],
  ])("reports nothing for %s", (_label, resolveDir) => {
    const captureException = vi.fn();

    expect(reportCrashDumps(resolveDir(), captureException)).toEqual({
      found: 0,
      reported: 0,
      pruned: 0,
    });
    expect(captureException).not.toHaveBeenCalled();
    expect(warn).not.toHaveBeenCalled();
  });

  it("logs a read failure that is not a missing directory", () => {
    writeFileSync(path.join(crashDumpsDir, "pending"), "not a directory");
    const captureException = vi.fn();

    expect(reportCrashDumps(crashDumpsDir, captureException)).toEqual({
      found: 0,
      reported: 0,
      pruned: 0,
    });
    expect(warn).toHaveBeenCalledTimes(1);
  });

  // Crashpad writes to `pending` on macOS and Linux, and to `reports` on
  // Windows, so a scan of one layout misses every dump on the other.
  it("lists dumps from both crashpad layouts, newest first", () => {
    writeDump("pending", "unix.dmp", 60);
    writeDump("reports", "windows.dmp", 5);
    writeDump("new", "still-writing.dmp", 1);
    writeFileSync(path.join(crashDumpsDir, "pending", "settings.dat"), "no");

    expect(listCrashDumps(crashDumpsDir).map((d) => d.fileName)).toEqual([
      "windows.dmp",
      "unix.dmp",
    ]);
  });

  it("captures one exception per dump and prunes the files", () => {
    writeDump("pending", "crash.dmp", 10);
    const captureException = vi.fn();

    const report = reportCrashDumps(crashDumpsDir, captureException);

    expect(report).toEqual({ found: 1, reported: 1, pruned: 1 });
    expect(captureException).toHaveBeenCalledTimes(1);
    expect(captureException.mock.calls[0][1]).toMatchObject({
      source: "main",
      type: "native-crash",
      dumpFileName: "crash.dmp",
      dumpCount: "1",
      $exception_fingerprint: `native-crash:${process.platform}`,
    });
    expect(readdirSync(path.join(crashDumpsDir, "pending"))).toHaveLength(0);
  });

  it("caps reporting of a backlog but still prunes every dump", () => {
    for (let index = 0; index < 8; index++) {
      writeDump("pending", `crash-${index}.dmp`, index * 10);
    }
    const captureException = vi.fn();

    const report = reportCrashDumps(crashDumpsDir, captureException);

    expect(report).toEqual({ found: 8, reported: 5, pruned: 8 });
    expect(
      captureException.mock.calls.map((call) => call[1].dumpFileName),
    ).toEqual([
      "crash-0.dmp",
      "crash-1.dmp",
      "crash-2.dmp",
      "crash-3.dmp",
      "crash-4.dmp",
    ]);
    expect(readdirSync(path.join(crashDumpsDir, "pending"))).toHaveLength(0);
  });
});
