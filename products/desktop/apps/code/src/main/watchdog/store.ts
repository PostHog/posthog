import fs from "node:fs";
import path from "node:path";
import type { WatchdogReport } from "@main/watchdog/types";

const fsPromises = fs.promises;

const BREADCRUMB_FILE = "breadcrumbs.jsonl";
const ROTATED_BREADCRUMB_FILE = "breadcrumbs.previous.jsonl";
const SESSION_FILE = "session.json";
const SUMMARY_FILE = "summary.json";
const REPORTS_DIR = "reports";

export interface SessionSentinel {
  pid: number;
  version: string;
  platform: string;
  startedAt: string;
}

/**
 * Everything the watchdog writes lives under one directory so a user can zip it
 * and attach it. Instances are cheap; the byte counter is the only state.
 */
export class WatchdogStore {
  private breadcrumbBytes: number | null = null;

  constructor(private readonly baseDirectory: string) {}

  get reportsDirectory(): string {
    return path.join(this.baseDirectory, REPORTS_DIR);
  }

  get breadcrumbPath(): string {
    return path.join(this.baseDirectory, BREADCRUMB_FILE);
  }

  async ensureDirectories(): Promise<void> {
    await fsPromises.mkdir(this.reportsDirectory, { recursive: true });
  }

  private async rotateBreadcrumbs(): Promise<void> {
    try {
      await fsPromises.rename(
        this.breadcrumbPath,
        path.join(this.baseDirectory, ROTATED_BREADCRUMB_FILE),
      );
    } catch {
      // Nothing to rotate yet.
    }
    this.breadcrumbBytes = 0;
  }

  /**
   * Breadcrumbs are the only record that survives a SIGKILL or a force quit, so
   * every sample is appended as it is taken rather than buffered.
   */
  async appendBreadcrumb(entry: unknown, maxBytes: number): Promise<void> {
    if (this.breadcrumbBytes === null) {
      try {
        this.breadcrumbBytes = (
          await fsPromises.stat(this.breadcrumbPath)
        ).size;
      } catch {
        this.breadcrumbBytes = 0;
      }
    }

    if (this.breadcrumbBytes >= maxBytes) {
      await this.rotateBreadcrumbs();
    }

    const line = `${JSON.stringify(entry)}\n`;
    await fsPromises.appendFile(this.breadcrumbPath, line, "utf-8");
    this.breadcrumbBytes =
      (this.breadcrumbBytes ?? 0) + Buffer.byteLength(line);
  }

  async readBreadcrumbTail(limit: number): Promise<string[]> {
    try {
      const content = await fsPromises.readFile(this.breadcrumbPath, "utf-8");
      return content.split("\n").filter(Boolean).slice(-limit);
    } catch {
      return [];
    }
  }

  async writeSessionSentinel(sentinel: SessionSentinel): Promise<void> {
    await this.ensureDirectories();
    await fsPromises.writeFile(
      path.join(this.baseDirectory, SESSION_FILE),
      JSON.stringify(sentinel, null, 2),
      "utf-8",
    );
  }

  /**
   * A sentinel left behind means the previous run never reached its shutdown
   * path: an OOM kill, a force quit, or a hard crash.
   */
  async takeStaleSessionSentinel(): Promise<SessionSentinel | null> {
    const filePath = path.join(this.baseDirectory, SESSION_FILE);
    try {
      const content = await fsPromises.readFile(filePath, "utf-8");
      await fsPromises.unlink(filePath).catch(() => {});
      return JSON.parse(content) as SessionSentinel;
    } catch {
      return null;
    }
  }

  /** Synchronous: the callers are exit handlers that will not await. */
  clearSessionSentinelSync(): void {
    try {
      fs.unlinkSync(path.join(this.baseDirectory, SESSION_FILE));
    } catch {
      // Already gone.
    }
  }

  /**
   * Report ids start with an ISO timestamp, so lexicographic order is
   * chronological.
   */
  private async readReportDirectoryNames(): Promise<string[]> {
    try {
      const entries = await fsPromises.readdir(this.reportsDirectory, {
        withFileTypes: true,
      });
      const names: string[] = [];
      for (const entry of entries) {
        if (entry.isDirectory()) {
          names.push(entry.name);
        }
      }
      return names.sort();
    } catch {
      return [];
    }
  }

  async createReportDirectory(id: string): Promise<string> {
    const directory = path.join(this.reportsDirectory, id);
    await fsPromises.mkdir(directory, { recursive: true });
    return directory;
  }

  async writeReportSummary(
    directory: string,
    summary: WatchdogReport,
  ): Promise<void> {
    await fsPromises.writeFile(
      path.join(directory, SUMMARY_FILE),
      JSON.stringify(summary, null, 2),
      "utf-8",
    );
  }

  /**
   * A report is a directory with a parsable `summary.json`. A capture killed
   * mid-write leaves the directory without one, so both listing and pruning go
   * through here and agree on what counts.
   */
  private async readReportSummary(
    name: string,
  ): Promise<WatchdogReport | null> {
    try {
      const content = await fsPromises.readFile(
        path.join(this.reportsDirectory, name, SUMMARY_FILE),
        "utf-8",
      );
      return JSON.parse(content) as WatchdogReport;
    } catch {
      return null;
    }
  }

  async listReports(): Promise<WatchdogReport[]> {
    const names = await this.readReportDirectoryNames();

    const summaries = await Promise.all(
      names.map((name) => this.readReportSummary(name)),
    );

    const found: WatchdogReport[] = [];
    for (const summary of summaries) {
      if (summary !== null) {
        found.push(summary);
      }
    }
    return found.sort((a, b) => b.at.localeCompare(a.at));
  }

  /**
   * Report directories can hold heap snapshots, so old ones cannot linger.
   * Directories with no valid `summary.json` are removed outright and never
   * counted against `maxReports`: otherwise a crash-truncated directory would
   * occupy a retention slot and displace a report `listReports` can still read.
   */
  async pruneReports(maxReports: number): Promise<string[]> {
    const names = await this.readReportDirectoryNames();
    const summaries = await Promise.all(
      names.map((name) => this.readReportSummary(name)),
    );

    const complete: string[] = [];
    const doomed: string[] = [];
    names.forEach((name, index) => {
      if (summaries[index] !== null) {
        complete.push(name);
      } else {
        doomed.push(name);
      }
    });
    doomed.push(
      ...complete.slice(0, Math.max(0, complete.length - maxReports)),
    );

    for (const name of doomed) {
      await fsPromises.rm(path.join(this.reportsDirectory, name), {
        recursive: true,
        force: true,
      });
    }
    return doomed;
  }
}

export function buildReportId(at: Date, trigger: string): string {
  return `${at.toISOString().replace(/[:.]/g, "-")}-${trigger}`;
}
