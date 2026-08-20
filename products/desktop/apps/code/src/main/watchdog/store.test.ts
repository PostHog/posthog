import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { WatchdogStore } from "@main/watchdog/store";
import type { WatchdogReport } from "@main/watchdog/types";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

let directory: string;
let store: WatchdogStore;

beforeEach(() => {
  directory = mkdtempSync(path.join(os.tmpdir(), "watchdog-store-test-"));
  store = new WatchdogStore(directory);
});

afterEach(() => {
  rmSync(directory, { recursive: true, force: true });
});

function writeReportDir(id: string): void {
  const reportDirectory = path.join(store.reportsDirectory, id);
  mkdirSync(reportDirectory, { recursive: true });
  const summary: WatchdogReport = {
    id,
    directory: reportDirectory,
    trigger: "manual",
    at: id,
    totalRssBytes: 0,
    thresholdBytes: 0,
    files: ["summary.json"],
  };
  writeFileSync(
    path.join(reportDirectory, "summary.json"),
    JSON.stringify(summary),
    "utf-8",
  );
}

/** A capture killed before summary.json is written. */
function writeTruncatedReportDir(id: string): void {
  mkdirSync(path.join(store.reportsDirectory, id), { recursive: true });
}

describe("WatchdogStore", () => {
  it("removes crash-truncated directories without spending a retention slot", async () => {
    writeReportDir("2026-01-01-a");
    writeReportDir("2026-01-02-b");
    // Its id sorts newest, so a raw count-and-slice would keep it and prune a
    // real report in its place.
    writeTruncatedReportDir("2026-01-03-incomplete");

    const pruned = await store.pruneReports(2);

    expect(pruned).toEqual(["2026-01-03-incomplete"]);
    const ids = (await store.listReports()).map((report) => report.id).sort();
    expect(ids).toEqual(["2026-01-01-a", "2026-01-02-b"]);
  });
});
