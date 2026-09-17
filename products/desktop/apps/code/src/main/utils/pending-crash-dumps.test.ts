import { mkdtempSync, readdirSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  listPendingCrashDumps,
  reportPendingCrashDumps,
} from "./pending-crash-dumps";

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

describe("pending crash dumps", () => {
  let pendingDir: string;

  function writeDump(fileName: string, ageSeconds: number): void {
    const filePath = path.join(pendingDir, fileName);
    writeFileSync(filePath, "minidump");
    const seconds = Date.now() / 1000 - ageSeconds;
    utimesSync(filePath, seconds, seconds);
  }

  beforeEach(() => {
    pendingDir = mkdtempSync(path.join(tmpdir(), "crash-dumps-"));
    warn.mockClear();
  });

  it.each([
    ["a missing directory", () => path.join(pendingDir, "absent")],
    ["an empty directory", () => pendingDir],
  ])("reports nothing for %s", (_label, resolveDir) => {
    const captureException = vi.fn();

    expect(reportPendingCrashDumps(resolveDir(), captureException)).toEqual({
      found: 0,
      reported: 0,
      pruned: 0,
    });
    expect(captureException).not.toHaveBeenCalled();
    expect(warn).not.toHaveBeenCalled();
  });

  it("logs a read failure that is not a missing directory", () => {
    const notADirectory = path.join(pendingDir, "pending");
    writeFileSync(notADirectory, "not a directory");
    const captureException = vi.fn();

    expect(reportPendingCrashDumps(notADirectory, captureException)).toEqual({
      found: 0,
      reported: 0,
      pruned: 0,
    });
    expect(warn).toHaveBeenCalledTimes(1);
  });

  it("lists only dumps, newest first", () => {
    writeDump("old.dmp", 60);
    writeDump("new.dmp", 5);
    writeFileSync(path.join(pendingDir, "settings.dat"), "not a dump");

    expect(listPendingCrashDumps(pendingDir).map((d) => d.fileName)).toEqual([
      "new.dmp",
      "old.dmp",
    ]);
  });

  it("captures one exception per dump and prunes the files", () => {
    writeDump("crash.dmp", 10);
    const captureException = vi.fn();

    const report = reportPendingCrashDumps(pendingDir, captureException);

    expect(report).toEqual({ found: 1, reported: 1, pruned: 1 });
    expect(captureException).toHaveBeenCalledTimes(1);
    expect(captureException.mock.calls[0][1]).toMatchObject({
      source: "main",
      type: "native-crash",
      dumpFileName: "crash.dmp",
      pendingDumpCount: "1",
      $exception_fingerprint: `native-crash:${process.platform}`,
    });
    expect(readdirSync(pendingDir)).toHaveLength(0);
  });

  it("caps reporting of a backlog but still prunes every dump", () => {
    for (let index = 0; index < 8; index++) {
      writeDump(`crash-${index}.dmp`, index * 10);
    }
    const captureException = vi.fn();

    const report = reportPendingCrashDumps(pendingDir, captureException);

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
    expect(readdirSync(pendingDir)).toHaveLength(0);
  });
});
