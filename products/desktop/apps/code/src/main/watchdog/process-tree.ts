import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

const PS_TIMEOUT_MS = 5_000;
const PS_MAX_BUFFER = 32 * 1024 * 1024;
const PS_ARGS = ["-axo", "pid=,ppid=,rss=,pcpu=,args="];

// `ps` gives us the whole command line, which is where an agent's identity
// lives. The shapes below are the ones credentials actually arrive in, but a
// denylist can never be complete — a bare positional secret still gets through,
// so a report is sensitive material regardless.
const SECRET_TOKEN =
  /\b(?:phx_|phc_|sk-ant-|sk-|ghp_|gho_|ghs_|github_pat_|xox[abposr]-|AKIA)[A-Za-z0-9_-]{8,}/g;
// The keyword has to be a whole `-`/`_` separated component, so `--api_secret`
// and `--session-token` are caught while `--keyboard-layout` is left alone.
const SECRET_WORD =
  "(?:key|token|secret|password|passwd|credentials?|bearer|connection[-_]?string)";
const SECRET_FLAG = new RegExp(
  `(--?(?:[\\w-]*[-_])?${SECRET_WORD}(?:[-_][\\w-]*)?[=\\s]+)(?:"[^"]*"|'[^']*'|[^\\s"']+)`,
  "gi",
);
// Header values survive `ps` either quoted (`sh -c` keeps the whole command in
// one arg) or already split into argv, so the value has to be matched without
// relying on the quotes being there.
const SECRET_HEADER =
  /((?:authorization|proxy-authorization|x-api-key|x-auth-token)\s*:\s*(?:bearer|basic|token|digest)?\s*)(?:"[^"]*"|'[^']*'|[^\s"']+)/gi;
// `FOO_TOKEN=…` from an inline env assignment, and `?access_token=…` from a URL.
const SECRET_ASSIGNMENT = new RegExp(
  `\\b((?:[\\w.-]*[-._])?${SECRET_WORD}(?:[-._][\\w.-]*)?=)(?:"[^"]*"|'[^']*'|[^\\s"']+)`,
  "gi",
);
// The password half of `postgres://user:pass@host/db`.
const URL_CREDENTIALS = /([a-z][\w+.-]*:\/\/[^\s:/@]+:)[^\s/@]+@/gi;

const PS_LINE = /^\s*(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)\s+(.*)$/;

export interface OsProcess {
  pid: number;
  ppid: number;
  rssBytes: number;
  cpuPercent: number;
  command: string;
}

export function redactCommand(command: string): string {
  return command
    .replace(SECRET_HEADER, "$1[redacted]")
    .replace(SECRET_FLAG, "$1[redacted]")
    .replace(SECRET_ASSIGNMENT, "$1[redacted]")
    .replace(URL_CREDENTIALS, "$1[redacted]@")
    .replace(SECRET_TOKEN, "[redacted]");
}

export function parsePsOutput(stdout: string): OsProcess[] {
  const processes: OsProcess[] = [];

  for (const line of stdout.split("\n")) {
    const match = PS_LINE.exec(line);
    if (!match) continue;

    processes.push({
      pid: Number.parseInt(match[1], 10),
      ppid: Number.parseInt(match[2], 10),
      // `ps` reports RSS in kilobytes on both macOS and Linux.
      rssBytes: Number.parseInt(match[3], 10) * 1024,
      cpuPercent: Number.parseFloat(match[4]),
      command: redactCommand(match[5].trim()),
    });
  }

  return processes;
}

/**
 * Every process descended from `rootPid`, including the root itself.
 *
 * Walking the tree from the Electron main process rather than trusting
 * `getAppMetrics()` is the point of this file: the workspace-server child and
 * the agent CLI processes it spawns are ordinary OS processes, so Electron
 * never reports them even when they hold most of the memory.
 */
export function collectDescendants(
  processes: OsProcess[],
  rootPid: number,
): OsProcess[] {
  const childrenByParent = new Map<number, OsProcess[]>();
  for (const proc of processes) {
    const siblings = childrenByParent.get(proc.ppid);
    if (siblings) {
      siblings.push(proc);
    } else {
      childrenByParent.set(proc.ppid, [proc]);
    }
  }

  const root = processes.find((proc) => proc.pid === rootPid);
  const collected = root ? [root] : [];
  const seen = new Set<number>(root ? [rootPid] : []);
  const queue = [rootPid];

  while (queue.length > 0) {
    const pid = queue.shift() as number;
    for (const child of childrenByParent.get(pid) ?? []) {
      // Guard against a pid cycle from a reparented process.
      if (seen.has(child.pid)) continue;
      seen.add(child.pid);
      collected.push(child);
      queue.push(child.pid);
    }
  }

  return collected;
}

/**
 * Returns null when the platform has no supported enumeration path, which the
 * caller surfaces in the report rather than silently under-reporting memory.
 */
export async function readProcessTree(
  rootPid: number,
): Promise<OsProcess[] | null> {
  if (process.platform === "win32") {
    return null;
  }

  const { stdout } = await execFileAsync("ps", PS_ARGS, {
    timeout: PS_TIMEOUT_MS,
    maxBuffer: PS_MAX_BUFFER,
  });
  return collectDescendants(parsePsOutput(stdout), rootPid);
}
