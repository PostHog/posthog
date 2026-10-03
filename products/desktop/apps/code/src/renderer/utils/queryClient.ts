import type { Task } from "@posthog/shared/domain-types";
import {
  focusManager,
  MutationCache,
  QueryCache,
  QueryClient,
} from "@tanstack/react-query";
import { logger } from "./logger";

const queryLog = logger.scope("react-query");

/**
 * A query that keeps failing refetches every poll interval; one line a minute
 * per query key keeps the log readable while an API is down.
 */
const FAILURE_LOG_INTERVAL_MS = 60_000;
/**
 * Query keys and error messages both carry caller-supplied detail, so a caller
 * that varies either one sidesteps the per-key throttle. Cap the lines written
 * per window, the keys retained, and the length of each so a burst of distinct
 * failures cannot flood the log or grow the map.
 */
const MAX_FAILURES_LOGGED_PER_INTERVAL = 50;
const MAX_THROTTLE_KEYS = 100;
const MAX_LOGGED_LENGTH = 200;

const lastFailureLogAt = new Map<string, number>();
let failureWindowStartedAt = 0;
let failuresSeenInWindow = 0;

function describeError(error: unknown): string {
  if (error instanceof Error) return `${error.name}: ${error.message}`;
  return String(error);
}

function truncate(value: string): string {
  if (value.length <= MAX_LOGGED_LENGTH) return value;
  return `${value.slice(0, MAX_LOGGED_LENGTH)}… (${value.length} chars)`;
}

function logFailure(kind: "query" | "mutation", key: string, error: unknown) {
  const shortKey = truncate(key);
  const message = truncate(describeError(error));
  const throttleKey = `${kind}:${shortKey}:${message}`;
  const now = Date.now();
  // Error messages can carry unique detail (ids, timestamps), so keys are
  // unbounded; drop the ones whose window has passed rather than keep them.
  for (const [storedKey, loggedAt] of lastFailureLogAt) {
    if (now - loggedAt >= FAILURE_LOG_INTERVAL_MS) {
      lastFailureLogAt.delete(storedKey);
    }
  }
  const last = lastFailureLogAt.get(throttleKey) ?? 0;
  if (now - last < FAILURE_LOG_INTERVAL_MS) return;

  if (now - failureWindowStartedAt >= FAILURE_LOG_INTERVAL_MS) {
    failureWindowStartedAt = now;
    failuresSeenInWindow = 0;
  }
  failuresSeenInWindow += 1;
  if (failuresSeenInWindow > MAX_FAILURES_LOGGED_PER_INTERVAL) {
    // One line saying the log is muted beats thousands saying why.
    if (failuresSeenInWindow === MAX_FAILURES_LOGGED_PER_INTERVAL + 1) {
      queryLog.warn("too many distinct failures, muting until the next minute");
    }
    return;
  }

  while (lastFailureLogAt.size >= MAX_THROTTLE_KEYS) {
    const oldest = lastFailureLogAt.keys().next().value;
    if (oldest === undefined) break;
    lastFailureLogAt.delete(oldest);
  }
  lastFailureLogAt.set(throttleKey, now);
  queryLog.warn(`${kind} failed`, { key: shortKey, error: message });
}

export const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error, query) =>
      logFailure("query", JSON.stringify(query.queryKey), error),
  }),
  mutationCache: new MutationCache({
    onError: (error, _variables, _context, mutation) =>
      logFailure(
        "mutation",
        JSON.stringify(mutation.options.mutationKey ?? "anonymous"),
        error,
      ),
  }),
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5,
      refetchOnWindowFocus: true,
    },
  },
});

// Electron renderers stay visible when the BrowserWindow loses OS focus, so
// `document.visibilitychange` (TanStack's default signal) never fires on
// app-switch. Listen to window `focus`/`blur` as well so refetchOnWindowFocus
// actually triggers when the user returns from an external browser.
focusManager.setEventListener((handleFocus) => {
  if (typeof window === "undefined") return;

  const onFocus = () => handleFocus(true);
  const onBlur = () => handleFocus(false);
  const onVisibilityChange = () => handleFocus(!document.hidden);

  window.addEventListener("focus", onFocus);
  window.addEventListener("blur", onBlur);
  document.addEventListener("visibilitychange", onVisibilityChange);

  return () => {
    window.removeEventListener("focus", onFocus);
    window.removeEventListener("blur", onBlur);
    document.removeEventListener("visibilitychange", onVisibilityChange);
  };
});

export function getCachedTask(taskId: string): Task | undefined {
  return queryClient
    .getQueriesData<Task[]>({ queryKey: ["tasks", "list"] })
    .flatMap(([, tasks]) => tasks ?? [])
    .find((t) => t.id === taskId);
}
