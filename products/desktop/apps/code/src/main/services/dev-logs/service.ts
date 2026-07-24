import { TypedEventEmitter } from "@posthog/shared";
import type ElectronLog from "electron-log";
import log from "electron-log/main";
import { inject, injectable } from "inversify";
import { DEV_FLAGS_SERVICE } from "../../di/tokens";
import type { DevFlagsService } from "../dev-flags/service";
import { DevLogsEvent, type DevLogsEvents, type LogEntry } from "./schemas";

const RING_BUFFER_SIZE = 1000;

@injectable()
export class DevLogsService extends TypedEventEmitter<DevLogsEvents> {
  private entries: LogEntry[] = [];
  private nextId = 1;
  private installed = false;

  constructor(
    @inject(DEV_FLAGS_SERVICE)
    private readonly flags: DevFlagsService,
  ) {
    super();
  }

  install(): void {
    if (this.installed) return;
    this.installed = true;

    const transport = ((message: ElectronLog.LogMessage) => {
      if (!this.flags.getFlags().devMode) return;
      const entry: LogEntry = {
        id: this.nextId++,
        level: message.level ?? "info",
        scope: message.scope,
        message: formatMessage(message.data),
        capturedAt: (message.date ?? new Date()).getTime(),
        source:
          message.variables?.processType === "renderer" ? "renderer" : "main",
      };
      this.entries.push(entry);
      if (this.entries.length > RING_BUFFER_SIZE) {
        this.entries.splice(0, this.entries.length - RING_BUFFER_SIZE);
      }
      this.emit(DevLogsEvent.Entry, entry);
    }) as ElectronLog.Transport;
    transport.level = "silly";
    transport.transforms = [];

    // electron-log allows arbitrary string transport names
    (log.transports as Record<string, ElectronLog.Transport>).devToolbar =
      transport;
  }

  // Detach the electron-log transport so capture is fully reversible when
  // developer mode is turned off.
  uninstall(): void {
    if (!this.installed) return;
    this.installed = false;
    (
      log.transports as Record<string, ElectronLog.Transport | undefined>
    ).devToolbar = undefined;
  }

  getSnapshot(): LogEntry[] {
    return [...this.entries];
  }

  clear(): void {
    this.entries = [];
  }
}

function formatMessage(data: unknown[]): string {
  return data
    .map((item) => {
      if (typeof item === "string") return item;
      if (item instanceof Error) return `${item.message}\n${item.stack ?? ""}`;
      try {
        return JSON.stringify(item);
      } catch {
        return String(item);
      }
    })
    .join(" ");
}
