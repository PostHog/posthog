import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { TypedEventEmitter } from "@posthog/shared";
import { injectable } from "inversify";
import { getUserDataDir } from "../../utils/env";
import { logger } from "../../utils/logger";
import {
  DEFAULT_DEV_FLAGS,
  type DevFlags,
  DevFlagsEvent,
  type DevFlagsEvents,
  devFlagsSchema,
} from "./schemas";

const log = logger.scope("dev-flags");

const FLAGS_FILE_NAME = "dev-flags.json";
export const DEV_FLAGS_CLI_PREFIX = "--posthog-code-flags=";

let cachedFlags: DevFlags | null = null;

function getFlagsFilePath(): string {
  return path.join(getUserDataDir(), FLAGS_FILE_NAME);
}

export function readDevFlagsSync(): DevFlags {
  if (cachedFlags) return cachedFlags;
  try {
    const raw = readFileSync(getFlagsFilePath(), "utf-8");
    const parsed = devFlagsSchema.safeParse(JSON.parse(raw));
    cachedFlags = parsed.success ? parsed.data : { ...DEFAULT_DEV_FLAGS };
    return cachedFlags;
  } catch {
    cachedFlags = { ...DEFAULT_DEV_FLAGS };
    return cachedFlags;
  }
}

export function encodeDevFlagsForArg(flags: DevFlags): string {
  return `${DEV_FLAGS_CLI_PREFIX}${encodeURIComponent(JSON.stringify(flags))}`;
}

@injectable()
export class DevFlagsService extends TypedEventEmitter<DevFlagsEvents> {
  private flags: DevFlags;

  constructor() {
    super();
    this.flags = readDevFlagsSync();
    log.info("Dev flags initialized", this.flags);
  }

  getFlags(): DevFlags {
    return { ...this.flags };
  }

  setDevMode(enabled: boolean): DevFlags {
    return this.update({ devMode: enabled });
  }

  private update(partial: Partial<DevFlags>): DevFlags {
    const next = { ...this.flags, ...partial };
    this.flags = next;
    cachedFlags = next;
    try {
      writeFileSync(getFlagsFilePath(), JSON.stringify(next, null, 2), "utf-8");
    } catch (error) {
      log.warn("Failed to persist dev flags", { error });
    }
    this.emit(DevFlagsEvent.Changed, { ...next });
    return { ...next };
  }
}
