import { inject, injectable, preDestroy } from "inversify";
import {
  SHELL_PROCESS_POLL_INTERVAL_MS,
  SHELL_PROCESS_READER,
  type ShellProcessReader,
} from "./identifiers";

export type ProcessNameListener = (processName: string | null) => void;

interface PollerEntry {
  intervalId: ReturnType<typeof setInterval>;
  sessionId: string;
  lastProcessName: string | null;
  listener: ProcessNameListener;
}

@injectable()
export class ShellProcessPoller {
  private readonly entries = new Map<string, PollerEntry>();

  constructor(
    @inject(SHELL_PROCESS_READER)
    private readonly reader: ShellProcessReader,
  ) {}

  start(
    key: string,
    sessionId: string,
    listener: ProcessNameListener,
    initialProcessName: string | null = null,
  ): void {
    if (this.entries.has(key)) return;

    const entry: PollerEntry = {
      intervalId: setInterval(
        () => void this.poll(key),
        SHELL_PROCESS_POLL_INTERVAL_MS,
      ),
      sessionId,
      lastProcessName: initialProcessName,
      listener,
    };
    this.entries.set(key, entry);

    void this.poll(key);
  }

  stop(key: string): void {
    const entry = this.entries.get(key);
    if (!entry) return;

    clearInterval(entry.intervalId);
    this.entries.delete(key);
  }

  @preDestroy()
  stopAll(): void {
    for (const key of this.entries.keys()) {
      this.stop(key);
    }
  }

  private async poll(key: string): Promise<void> {
    const entry = this.entries.get(key);
    if (!entry) return;

    const processName = await this.reader.getProcess({
      sessionId: entry.sessionId,
    });

    const current = this.entries.get(key);
    if (!current) return;

    const next = processName ?? null;
    if (next === current.lastProcessName) return;

    current.lastProcessName = next;
    current.listener(next);
  }
}
