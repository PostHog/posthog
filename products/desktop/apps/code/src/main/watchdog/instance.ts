import type { MemoryWatchdog } from "@main/watchdog/watchdog";

let instance: MemoryWatchdog | null = null;

/**
 * The watchdog is constructed in `main/index.ts`, where Electron is in scope.
 * The menu needs to reach the same instance without importing the composition
 * root back, which would close an import cycle.
 */
export function setMemoryWatchdog(watchdog: MemoryWatchdog): void {
  instance = watchdog;
}

export function getMemoryWatchdog(): MemoryWatchdog | null {
  return instance;
}
