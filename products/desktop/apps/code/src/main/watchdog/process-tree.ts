import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

const PS_TIMEOUT_MS = 5_000;
const PS_MAX_BUFFER = 32 * 1024 * 1024;
const PS_ARGS = ["-axo", "pid=,ppid=,rss=,pcpu=,args="];

// `ps` gives us the whole command line, which is where an agent's identity
// lives. Anything that smells like a credential is stripped before it can reach
// a report the user might attach to an issue.
const SECRET_TOKEN =
  /\b(?:phx_|phc_|sk-ant-|sk-|ghp_|gho_|ghs_|github_pat_)[A-Za-z0-9_-]{8,}/g;
const SECRET_FLAG = /(--(?:api-?key|token|secret|password)[=\s]+)\S+/gi;

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
    .replace(SECRET_FLAG, "$1[redacted]")
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
