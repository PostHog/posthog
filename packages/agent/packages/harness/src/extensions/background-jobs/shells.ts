/**
 * Background shells and monitors: long-running commands the agent starts and keeps working beside, such as a
 * dev server, a mobile app bundler, a test watcher, or `gh pr checks --watch`.
 *
 * A shell is a background job whose work is waiting for its process to exit, so its exit reaches the agent
 * through `startBackgroundJob` and `cancel_background_job` stops it like any other job. Its output is kept in
 * memory; the agent reads what is new since its last read. A monitor watches a shell's output for a pattern
 * and wakes the agent with the matching lines, so the agent reacts to logs as they arrive instead of polling.
 */

import { type ChildProcess, spawn } from "node:child_process";
import { stripVTControlCharacters } from "node:util";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { deliverBackgroundMessage, startBackgroundJob } from "./jobs";

export const BACKGROUND_SHELL_MESSAGE_TYPE = "background-shell";

// Output kept per shell. Older lines drop off; the agent is told how many it missed.
const MAX_LINES = 5000;
const MAX_LINE_LENGTH = 2000;
// A read returns at most this many lines, so one call cannot flood the context.
export const MAX_READ_LINES = 200;
// Matches arriving together are sent as one message, and a monitor waits this long between messages.
const MONITOR_SETTLE_MS = 1500;
const MONITOR_MIN_INTERVAL_MS = 10_000;
const MONITOR_MAX_LINES = 20;
// A stopped shell gets this long to exit after SIGTERM before SIGKILL.
const STOP_GRACE_MS = 3000;

export interface Monitor {
  id: string;
  pattern: RegExp;
  label: string;
  matches: number;
}

interface MonitorState extends Monitor {
  pending: string[];
  lastSentAt: number;
  timer: ReturnType<typeof setTimeout> | null;
}

export interface ShellSummary {
  id: string;
  command: string;
  running: boolean;
  exitCode: number | null;
  startedAt: number;
  lines: number;
  unread: number;
  monitors: Monitor[];
}

interface ShellState {
  id: string;
  jobId: string;
  command: string;
  child: ChildProcess;
  startedAt: number;
  running: boolean;
  exitCode: number | null;
  // The kept lines are lines[0] = line number `dropped`, and so on.
  lines: string[];
  dropped: number;
  // Line number up to which the agent has read.
  readTo: number;
  partial: { stdout: string; stderr: string };
  monitors: MonitorState[];
}

export class BackgroundShells {
  private readonly shells = new Map<string, ShellState>();
  private nextShell = 1;
  private nextMonitor = 1;

  private readonly settleMs: number;
  private readonly minIntervalMs: number;

  constructor(
    private readonly pi: Pick<ExtensionAPI, "sendMessage">,
    // Called whenever a shell or monitor starts, stops, or changes, so a status line can follow.
    private readonly onChange: () => void = () => {},
    timing: { settleMs?: number; minIntervalMs?: number } = {},
  ) {
    this.settleMs = timing.settleMs ?? MONITOR_SETTLE_MS;
    this.minIntervalMs = timing.minIntervalMs ?? MONITOR_MIN_INTERVAL_MS;
  }

  start(
    command: string,
    cwd: string,
    monitors: { pattern: string; label?: string }[] = [],
  ): { id: string; ack: string } {
    // A bad pattern fails before anything starts.
    for (const monitor of monitors) new RegExp(monitor.pattern, "i");
    const id = `shell-${this.nextShell++}`;
    const child = spawn(process.env.SHELL || "/bin/bash", ["-lc", command], {
      cwd,
      env: process.env,
      // Its own process group, so stopping it stops what it started too.
      detached: true,
      stdio: ["pipe", "pipe", "pipe"],
    });
    const shell: ShellState = {
      id,
      jobId: "",
      command,
      child,
      startedAt: Date.now(),
      running: true,
      exitCode: null,
      lines: [],
      dropped: 0,
      readTo: 0,
      partial: { stdout: "", stderr: "" },
      monitors: [],
    };
    this.shells.set(id, shell);
    for (const monitor of monitors)
      this.addMonitor(id, monitor.pattern, monitor.label);

    const take = (stream: "stdout" | "stderr") => (chunk: Buffer) => {
      const text = shell.partial[stream] + chunk.toString("utf8");
      const parts = text.split(/\r?\n/);
      shell.partial[stream] = parts.pop() ?? "";
      for (const line of parts) this.append(shell, line);
    };
    child.stdout?.on("data", take("stdout"));
    child.stderr?.on("data", take("stderr"));

    const exited = new Promise<number | null>((resolve, reject) => {
      child.on("error", reject);
      child.on("close", (code) => {
        for (const stream of ["stdout", "stderr"] as const) {
          if (shell.partial[stream]) this.append(shell, shell.partial[stream]);
          shell.partial[stream] = "";
        }
        shell.running = false;
        shell.exitCode = code;
        for (const monitor of shell.monitors) this.flush(shell, monitor);
        this.onChange();
        resolve(code);
      });
    });

    const job = startBackgroundJob({
      pi: this.pi,
      label: `shell ${id}: ${command}`,
      work: (signal) => {
        signal.addEventListener("abort", () => this.kill(shell), {
          once: true,
        });
        return exited;
      },
      onSuccess: (code) => {
        const tail = this.tail(shell, 20);
        return [
          `Exited with code ${code ?? "unknown"}.`,
          tail.length ? `Last output:\n${tail.join("\n")}` : "No output.",
        ].join("\n\n");
      },
    });
    shell.jobId = job.jobId;
    this.onChange();
    return {
      id,
      ack: `Started ${id} in the background: ${command}\nRead its output with shell_output; you'll be told when it exits${monitors.length ? " or a monitor matches" : ""}.`,
    };
  }

  // Lines the agent has not read yet, oldest first, up to `limit`; or the last `limit` lines with `tail`.
  read(
    id: string,
    {
      limit = MAX_READ_LINES,
      tail = false,
    }: { limit?: number; tail?: boolean } = {},
  ): { lines: string[]; missed: number; more: number } | null {
    const shell = this.shells.get(id);
    if (!shell) return null;
    const end = shell.dropped + shell.lines.length;
    if (tail) {
      shell.readTo = end;
      return { lines: this.tail(shell, limit), missed: 0, more: 0 };
    }
    const from = Math.max(shell.readTo, shell.dropped);
    const to = Math.min(end, from + Math.min(limit, MAX_READ_LINES));
    const lines = shell.lines.slice(from - shell.dropped, to - shell.dropped);
    const missed = from - shell.readTo;
    shell.readTo = to;
    return { lines, missed, more: end - to };
  }

  write(id: string, text: string): boolean {
    const shell = this.shells.get(id);
    if (!shell?.running || !shell.child.stdin?.writable) return false;
    shell.child.stdin.write(text);
    return true;
  }

  stop(id: string): boolean {
    const shell = this.shells.get(id);
    if (!shell?.running) return false;
    this.kill(shell);
    return true;
  }

  addMonitor(id: string, pattern: string, label?: string): Monitor | null {
    const shell = this.shells.get(id);
    if (!shell) return null;
    const monitor: MonitorState = {
      id: `monitor-${this.nextMonitor++}`,
      pattern: new RegExp(pattern, "i"),
      label: label || pattern,
      matches: 0,
      pending: [],
      lastSentAt: 0,
      timer: null,
    };
    shell.monitors.push(monitor);
    this.onChange();
    return summary(monitor);
  }

  removeMonitor(monitorId: string): boolean {
    for (const shell of this.shells.values()) {
      const index = shell.monitors.findIndex((m) => m.id === monitorId);
      if (index < 0) continue;
      const [monitor] = shell.monitors.splice(index, 1);
      if (monitor.timer) clearTimeout(monitor.timer);
      this.onChange();
      return true;
    }
    return false;
  }

  list(): ShellSummary[] {
    return [...this.shells.values()].map((shell) => ({
      id: shell.id,
      command: shell.command,
      running: shell.running,
      exitCode: shell.exitCode,
      startedAt: shell.startedAt,
      lines: shell.dropped + shell.lines.length,
      unread: shell.dropped + shell.lines.length - shell.readTo,
      monitors: shell.monitors.map(summary),
    }));
  }

  // "2 shells · 1 monitor" for running shells and their monitors, or undefined when none run.
  status(): string | undefined {
    const running = [...this.shells.values()].filter((s) => s.running);
    if (running.length === 0) return undefined;
    const monitors = running.reduce((sum, s) => sum + s.monitors.length, 0);
    const plural = (count: number, noun: string) =>
      `${count} ${noun}${count === 1 ? "" : "s"}`;
    return [
      plural(running.length, "shell"),
      ...(monitors > 0 ? [plural(monitors, "monitor")] : []),
    ].join(" · ");
  }

  stopAll(): void {
    for (const shell of this.shells.values())
      if (shell.running) this.kill(shell);
  }

  private append(shell: ShellState, raw: string): void {
    const line = stripVTControlCharacters(raw).slice(0, MAX_LINE_LENGTH);
    shell.lines.push(line);
    if (shell.lines.length > MAX_LINES) {
      shell.lines.shift();
      shell.dropped++;
    }
    for (const monitor of shell.monitors) {
      if (!monitor.pattern.test(line)) continue;
      monitor.matches++;
      monitor.pending.push(line);
      this.schedule(shell, monitor);
    }
  }

  private schedule(shell: ShellState, monitor: MonitorState): void {
    if (monitor.timer) return;
    const wait = Math.max(
      this.settleMs,
      monitor.lastSentAt + this.minIntervalMs - Date.now(),
    );
    monitor.timer = setTimeout(() => {
      monitor.timer = null;
      this.flush(shell, monitor);
    }, wait);
    monitor.timer.unref?.();
  }

  private flush(shell: ShellState, monitor: MonitorState): void {
    if (monitor.timer) {
      clearTimeout(monitor.timer);
      monitor.timer = null;
    }
    if (monitor.pending.length === 0) return;
    const lines = monitor.pending.splice(0);
    const shown = lines.slice(-MONITOR_MAX_LINES);
    monitor.lastSentAt = Date.now();
    deliverBackgroundMessage(this.pi, {
      customType: BACKGROUND_SHELL_MESSAGE_TYPE,
      content: [
        `Monitor "${monitor.label}" (${monitor.id}) matched ${lines.length} line${lines.length === 1 ? "" : "s"} in ${shell.id} (${shell.command}):`,
        ...(lines.length > shown.length
          ? [`(${lines.length - shown.length} earlier matches not shown)`]
          : []),
        ...shown,
      ].join("\n"),
      display: true,
      details: { shellId: shell.id, monitorId: monitor.id, lines: shown },
    });
  }

  private kill(shell: ShellState): void {
    if (!shell.running || shell.child.pid === undefined) return;
    const pid = shell.child.pid;
    const signal = (name: NodeJS.Signals) => {
      try {
        process.kill(-pid, name);
      } catch {
        shell.child.kill(name);
      }
    };
    signal("SIGTERM");
    setTimeout(() => {
      if (shell.running) signal("SIGKILL");
    }, STOP_GRACE_MS).unref?.();
  }

  private tail(shell: ShellState, count: number): string[] {
    return shell.lines.slice(-count);
  }
}

function summary({ id, pattern, label, matches }: MonitorState): Monitor {
  return { id, pattern, label, matches };
}
