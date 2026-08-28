import {
  closeSync,
  existsSync,
  fstatSync,
  mkdirSync,
  openSync,
  readSync,
  renameSync,
  unlinkSync,
} from "node:fs";
import os from "node:os";
import { join } from "node:path";
import { initOtelTransport } from "@main/utils/otel-log-transport";
import type ElectronLog from "electron-log";
import log from "electron-log/main";
import { isDevBuild } from "./env";

const isDev = process.env.NODE_ENV === "development" || isDevBuild();
const LOG_DIR = join(
  os.homedir(),
  ".posthog-code",
  isDev ? "logs-dev" : "logs",
);
const LOG_FILE = "main.log";
const NETWORK_LOG_FILE = "network.log";
const MAX_ARCHIVES = 3;
const MAX_LOG_SIZE = 10 * 1024 * 1024;

mkdirSync(LOG_DIR, { recursive: true });

function createArchiveLogFn(
  prefix: string,
): (oldLogFile: ElectronLog.LogFile) => void {
  return (oldLogFile) => {
    const archivePath = (n: number) => join(LOG_DIR, `${prefix}.${n}.log`);

    try {
      const lastArchive = archivePath(MAX_ARCHIVES);
      if (existsSync(lastArchive)) {
        unlinkSync(lastArchive);
      }

      for (let i = MAX_ARCHIVES - 1; i >= 1; i--) {
        const from = archivePath(i);
        if (existsSync(from)) {
          renameSync(from, archivePath(i + 1));
        }
      }

      renameSync(oldLogFile.path, archivePath(1));
    } catch {
      // Best-effort rotation
    }
  };
}

log.initialize();

log.transports.file.resolvePathFn = () => join(LOG_DIR, LOG_FILE);
log.transports.file.maxSize = MAX_LOG_SIZE;
log.transports.file.archiveLogFn = createArchiveLogFn("main");

const level = isDev ? "debug" : "info";
log.transports.file.level = level;
log.transports.console.level = level;
log.transports.ipc.level = level;
log.transports.otel = initOtelTransport(level);

// File-only instance: console off, ipc off (defaults to active in dev and
// would spam renderer devtools), no otel so network lines stay out of OTLP
// ingestion, no initialize() since nothing routes to it over renderer IPC.
export const networkLog = log.create({ logId: "network" });
networkLog.transports.file.resolvePathFn = () =>
  join(LOG_DIR, NETWORK_LOG_FILE);
networkLog.transports.file.maxSize = MAX_LOG_SIZE;
networkLog.transports.file.archiveLogFn = createArchiveLogFn("network");
networkLog.transports.file.level = "info";
networkLog.transports.console.level = false;
networkLog.transports.ipc.level = false;

export const logger = log;
export type Logger = typeof logger;
export type ScopedLogger = ReturnType<typeof logger.scope>;

export function getLogFilePath(): string {
  return join(LOG_DIR, LOG_FILE);
}

export function getNetworkLogFilePath(): string {
  return join(LOG_DIR, NETWORK_LOG_FILE);
}

export function getChromiumLogFilePath(): string | undefined {
  return process.env.POSTHOG_CODE_CHROMIUM_LOG_PATH;
}

const CHROMIUM_LOG_TAIL_BYTES = 32 * 1024;

/**
 * Read the last ~32 KB of the Chromium internal log file. Used by crash
 * handlers to attach the tail to OTEL/electron-log so PostHog gets the native
 * V8/GPU output around a renderer death — Chromium writes chromium.log
 * directly from native code and never goes through electron-log otherwise.
 */
export function readChromiumLogTail(): string | undefined {
  const path = getChromiumLogFilePath();
  if (!path) return undefined;

  let fd: number | undefined;
  try {
    fd = openSync(path, "r");
    const { size } = fstatSync(fd);
    if (size === 0) return undefined;
    const length = Math.min(size, CHROMIUM_LOG_TAIL_BYTES);
    const buf = Buffer.alloc(length);
    readSync(fd, buf, 0, length, size - length);
    return buf.toString("utf8");
  } catch {
    return undefined;
  } finally {
    if (fd !== undefined) {
      try {
        closeSync(fd);
      } catch {
        // Best-effort close
      }
    }
  }
}
