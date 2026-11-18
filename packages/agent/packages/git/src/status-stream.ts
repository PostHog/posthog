import { spawn } from "node:child_process";
import { PERFORMANCE_CONFIG } from "./client";
import { getCleanEnv } from "./operation-manager";

export interface StreamedGitStatus {
  isClean: boolean;
  staged: string[];
  modified: string[];
  created: string[];
  deleted: string[];
  untracked: string[];
  overflowedDirs: string[];
  totalUntrackedSeen: number;
  totalUntrackedTruncated: boolean;
}

export interface StreamStatusOptions {
  signal?: AbortSignal;
  perDirUntrackedCap?: number;
  totalUntrackedCap?: number;
  gitBinary?: string;
}

const DEFAULT_PER_DIR_CAP = 1_000;
const DEFAULT_TOTAL_CAP = 50_000;

export function streamGitStatus(
  baseDir: string,
  options: StreamStatusOptions = {},
): Promise<StreamedGitStatus> {
  const perDirCap = options.perDirUntrackedCap ?? DEFAULT_PER_DIR_CAP;
  const totalCap = options.totalUntrackedCap ?? DEFAULT_TOTAL_CAP;
  const binary = options.gitBinary ?? "git";

  return new Promise((resolve, reject) => {
    const args = [
      ...PERFORMANCE_CONFIG.flatMap((cfg) => ["-c", cfg]),
      "status",
      "--porcelain=v1",
      "-z",
      "--untracked-files=all",
      "--no-renames",
    ];

    const child = spawn(binary, args, {
      cwd: baseDir,
      env: { ...getCleanEnv(), GIT_OPTIONAL_LOCKS: "0" },
    });

    const staged: string[] = [];
    const modified: string[] = [];
    const created: string[] = [];
    const deleted: string[] = [];
    const untracked: string[] = [];
    const dirCounts = new Map<string, number>();
    const collapsedDirs = new Set<string>();
    let totalUntrackedSeen = 0;
    let totalUntrackedTruncated = false;

    let buffer = "";
    let stderr = "";
    let settled = false;

    const settle = (fn: () => void) => {
      if (settled) return;
      settled = true;
      fn();
    };

    const onAbort = () => {
      child.kill("SIGTERM");
    };

    if (options.signal) {
      if (options.signal.aborted) {
        child.kill("SIGTERM");
        settle(() => reject(new DOMException("Aborted", "AbortError")));
        return;
      }
      options.signal.addEventListener("abort", onAbort, { once: true });
    }

    const consumeEntry = (entry: string) => {
      if (entry.length < 3) return;
      const x = entry[0];
      const y = entry[1];
      const filePath = entry.slice(3);
      if (!filePath) return;

      if (x === "?" && y === "?") {
        totalUntrackedSeen++;
        if (untracked.length >= totalCap) {
          totalUntrackedTruncated = true;
          return;
        }
        if (isUnderCollapsed(filePath, collapsedDirs)) return;

        const ancestors = ancestorDirs(filePath);
        let triggered: string | null = null;
        for (const dir of ancestors) {
          const count = (dirCounts.get(dir) ?? 0) + 1;
          dirCounts.set(dir, count);
          if (count > perDirCap && !triggered) {
            triggered = dir;
          }
        }
        if (triggered) {
          collapsedDirs.add(triggered);
          return;
        }
        untracked.push(filePath);
        return;
      }

      if (x === "A") created.push(filePath);
      if (x === "D" || y === "D") deleted.push(filePath);
      if (y === "M" || y === "T") modified.push(filePath);
      if (x !== " " && x !== "?") staged.push(filePath);
    };

    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      buffer += chunk;
      while (true) {
        const nullIdx = buffer.indexOf("\0");
        if (nullIdx === -1) break;
        const entry = buffer.slice(0, nullIdx);
        buffer = buffer.slice(nullIdx + 1);
        if (entry) consumeEntry(entry);
      }
    });

    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk: string) => {
      stderr += chunk;
    });

    child.on("error", (err) => {
      options.signal?.removeEventListener("abort", onAbort);
      settle(() => reject(err));
    });

    child.on("close", (code) => {
      options.signal?.removeEventListener("abort", onAbort);
      if (options.signal?.aborted) {
        settle(() => reject(new DOMException("Aborted", "AbortError")));
        return;
      }
      if (code !== 0) {
        settle(() =>
          reject(
            new Error(
              `git status exited with code ${code}: ${stderr.trim() || "unknown error"}`,
            ),
          ),
        );
        return;
      }
      const isClean =
        staged.length === 0 &&
        modified.length === 0 &&
        created.length === 0 &&
        deleted.length === 0 &&
        untracked.length === 0 &&
        collapsedDirs.size === 0;
      settle(() =>
        resolve({
          isClean,
          staged,
          modified,
          created,
          deleted,
          untracked,
          overflowedDirs: [...collapsedDirs],
          totalUntrackedSeen,
          totalUntrackedTruncated,
        }),
      );
    });
  });
}

function ancestorDirs(filePath: string): string[] {
  const result: string[] = [];
  let idx = filePath.indexOf("/");
  while (idx !== -1) {
    result.push(filePath.slice(0, idx));
    idx = filePath.indexOf("/", idx + 1);
  }
  return result;
}

function isUnderCollapsed(
  filePath: string,
  collapsedDirs: Set<string>,
): boolean {
  if (collapsedDirs.size === 0) return false;
  for (const dir of ancestorDirs(filePath)) {
    if (collapsedDirs.has(dir)) return true;
  }
  return false;
}
