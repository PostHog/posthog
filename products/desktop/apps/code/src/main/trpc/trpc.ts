import {
  publicProcedure as baseProcedure,
  router as baseRouter,
  middleware,
} from "@posthog/host-trpc/trpc";
import log from "electron-log/main";

const CALL_RATE_WINDOW_MS = 2000;
const CALL_RATE_THRESHOLD = 50;

const callCounts: Record<string, number[]> = {};

const ipcTimingEnvEnabled = process.env.IPC_TIMINGS === "true";
const ipcTimingBootMs = 15_000;
const bootTime = Date.now();

const callRateMonitor = middleware(async ({ path, next, type }) => {
  const bootWindowOpen = Date.now() - bootTime < ipcTimingBootMs;
  const envBootTiming = ipcTimingEnvEnabled && bootWindowOpen;
  const start = envBootTiming ? performance.now() : 0;

  if (envBootTiming) {
    log.info(`[ipc-timing] >> ${type} ${path}`);
  }

  if (process.env.NODE_ENV === "development") {
    const now = Date.now();
    if (!callCounts[path]) {
      callCounts[path] = [];
    }

    const timestamps = callCounts[path];
    timestamps.push(now);

    const cutoff = now - CALL_RATE_WINDOW_MS;
    while (timestamps.length > 0 && timestamps[0] < cutoff) {
      timestamps.shift();
    }

    if (timestamps.length >= CALL_RATE_THRESHOLD) {
      log.warn(
        `[ipc-rate] ${type} ${path} called ${timestamps.length} times in ${CALL_RATE_WINDOW_MS}ms`,
      );
    }
  }

  try {
    return await next();
  } finally {
    if (envBootTiming) {
      const durationMs = performance.now() - start;
      log.info(`[ipc-timing] << ${type} ${path}: ${durationMs.toFixed(0)}ms`);
    }
  }
});

export const router = baseRouter;
export const publicProcedure = baseProcedure.use(callRateMonitor);
export { middleware };
