import { constants as fsConstants } from "node:fs";
import { access, open, stat, writeFile } from "node:fs/promises";
import { constants as osConstants } from "node:os";
import { dirname } from "node:path";
import type { ProcessKilledParams } from "../acp-extensions";
import type { Logger } from "../utils/logger";

export const MEMORY_WATCHDOG_EVENTS_PATH = "/tmp/posthog-memory-watchdog.jsonl";
export const AGENT_CLI_PID_PATH = "/tmp/agent-cli.pid";
export const VM_CLI_OOM_SCORE_ADJ = 500;
const POLL_INTERVAL_MS = 1_000;
const MAX_READ_BYTES = 1024 * 1024;
const NEWLINE = 0x0a;

export class JsonlTail {
  private offset = 0;
  private remainder: Buffer = Buffer.alloc(0);

  get position(): number {
    return this.offset;
  }

  reset(): void {
    this.offset = 0;
    this.remainder = Buffer.alloc(0);
  }

  consume(chunk: Buffer): Record<string, unknown>[] {
    this.offset += chunk.length;
    const data =
      this.remainder.length > 0
        ? Buffer.concat([this.remainder, chunk])
        : chunk;
    const records: Record<string, unknown>[] = [];
    let lineStart = 0;
    let newlineIndex = data.indexOf(NEWLINE, lineStart);
    while (newlineIndex !== -1) {
      const record = parseJsonLine(data.subarray(lineStart, newlineIndex));
      if (record) records.push(record);
      lineStart = newlineIndex + 1;
      newlineIndex = data.indexOf(NEWLINE, lineStart);
    }
    this.remainder = Buffer.from(data.subarray(lineStart));
    return records;
  }
}

function parseJsonLine(line: Buffer): Record<string, unknown> | null {
  const text = line.toString("utf8").trim();
  if (!text) return null;
  try {
    const parsed: unknown = JSON.parse(text);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function signalName(value: unknown): string | null {
  if (typeof value === "string" && value) return value;
  const signal = finiteNumber(value);
  if (signal === null) return null;
  const name = Object.entries(osConstants.signals).find(
    ([, number]) => number === signal,
  )?.[0];
  return name ?? String(signal);
}

function recordTime(value: unknown): string {
  const seconds = finiteNumber(value);
  return new Date(seconds === null ? Date.now() : seconds * 1000).toISOString();
}

export function toProcessKilledParams(
  record: Record<string, unknown>,
): ProcessKilledParams | null {
  if (record.event !== "kill") return null;
  const pid = finiteNumber(record.pid);
  const treeRssBytes = finiteNumber(record.tree_rss);
  const memoryCurrentBytes = finiteNumber(record.current);
  const memoryLimitBytes = finiteNumber(record.limit);
  const signal = signalName(record.signal);
  if (
    pid === null ||
    typeof record.comm !== "string" ||
    treeRssBytes === null ||
    memoryCurrentBytes === null ||
    memoryLimitBytes === null ||
    signal === null
  ) {
    return null;
  }
  return {
    pid,
    comm: record.comm,
    treeRssBytes,
    memoryCurrentBytes,
    memoryLimitBytes,
    signal,
    at: recordTime(record.ts),
  };
}

export function isTaskRunSandbox(env: NodeJS.ProcessEnv): boolean {
  return Boolean(env.POSTHOG_TASK_RUN_ID);
}

export class MemoryWatchdogKillReader {
  private readonly tail = new JsonlTail();
  private inode: number | null = null;
  private reads: Promise<unknown> = Promise.resolve();

  constructor(readonly path: string = MEMORY_WATCHDOG_EVENTS_PATH) {}

  // Parallel tool calls run their hooks at the same time. Two overlapping
  // reads would read from the same offset and report the same kills twice.
  readNewKills(): Promise<ProcessKilledParams[]> {
    const read = this.reads.then(() => this.readOnce());
    this.reads = read.catch(() => undefined);
    return read;
  }

  private async readOnce(): Promise<ProcessKilledParams[]> {
    let size: number;
    let inode: number;
    try {
      const stats = await stat(this.path);
      size = stats.size;
      inode = stats.ino;
    } catch {
      return [];
    }
    if (this.inode !== null && inode !== this.inode) this.tail.reset();
    this.inode = inode;
    if (size < this.tail.position) this.tail.reset();
    if (size === this.tail.position) return [];
    const length = Math.min(size - this.tail.position, MAX_READ_BYTES);
    const handle = await open(this.path, "r");
    try {
      const buffer = Buffer.alloc(length);
      const { bytesRead } = await handle.read(
        buffer,
        0,
        length,
        this.tail.position,
      );
      return this.tail
        .consume(buffer.subarray(0, bytesRead))
        .map(toProcessKilledParams)
        .filter((params): params is ProcessKilledParams => params !== null);
    } finally {
      await handle.close();
    }
  }
}

export interface MemoryWatchdogWatcherOptions {
  onProcessKilled: (params: ProcessKilledParams) => void;
  logger: Logger;
  path?: string;
  intervalMs?: number;
}

export class MemoryWatchdogWatcher {
  private readonly reader: MemoryWatchdogKillReader;
  private readonly intervalMs: number;
  private timer: ReturnType<typeof setInterval> | null = null;
  private polling = false;

  constructor(private readonly options: MemoryWatchdogWatcherOptions) {
    this.reader = new MemoryWatchdogKillReader(options.path);
    this.intervalMs = options.intervalMs ?? POLL_INTERVAL_MS;
  }

  async start(): Promise<boolean> {
    if (this.timer) return true;
    try {
      await access(dirname(this.reader.path), fsConstants.W_OK);
    } catch {
      return false;
    }
    this.timer = setInterval(() => {
      void this.poll();
    }, this.intervalMs);
    this.timer.unref?.();
    return true;
  }

  stop(): void {
    if (!this.timer) return;
    clearInterval(this.timer);
    this.timer = null;
  }

  async poll(): Promise<void> {
    if (this.polling) return;
    this.polling = true;
    try {
      for (const params of await this.reader.readNewKills()) {
        this.options.onProcessKilled(params);
      }
    } catch (error) {
      this.options.logger.debug("Memory watchdog events read failed", {
        error: error instanceof Error ? error.message : String(error),
      });
    } finally {
      this.polling = false;
    }
  }
}

export class CliProcessRegistry {
  private readonly pids = new Set<number>();
  private writes: Promise<void> = Promise.resolve();

  constructor(
    private readonly env: NodeJS.ProcessEnv,
    private readonly pidPath: string = AGENT_CLI_PID_PATH,
  ) {}

  spawned(pid: number): Promise<void> {
    this.pids.add(pid);
    return this.enqueue(async () => {
      await this.writePidFile();
      if (this.env.POSTHOG_SANDBOX_RUNTIME !== "vm") return;
      await writeFile(
        `/proc/${pid}/oom_score_adj`,
        String(VM_CLI_OOM_SCORE_ADJ),
      ).catch(() => undefined);
    });
  }

  exited(pid: number): Promise<void> {
    this.pids.delete(pid);
    return this.enqueue(() => this.writePidFile());
  }

  private enqueue(task: () => Promise<void>): Promise<void> {
    this.writes = this.writes.then(task, task);
    return this.writes;
  }

  private async writePidFile(): Promise<void> {
    const content = [...this.pids].map((pid) => `${pid}\n`).join("");
    await writeFile(this.pidPath, content).catch(() => undefined);
  }
}
