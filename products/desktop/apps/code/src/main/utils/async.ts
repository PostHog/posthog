import { logger } from "./logger";

export { withTimeout } from "@posthog/shared";

const log = logger.scope("async-utils");

/**
 * Races a subscribe-style promise against a timeout. If the timeout wins,
 * any late-arriving subscription is torn down via its `unsubscribe()` method
 * so the underlying resource (e.g. FSEvents/inotify fd, callback closure)
 * does not leak.
 *
 * The late teardown is fire-and-forget: the caller does not await it. Errors
 * during teardown (or a late rejection of the subscribe promise) are logged
 * at warn level with `label` for diagnostic context.
 */
export async function subscribeWithTimeout<
  T extends { unsubscribe(): Promise<unknown> },
>(
  subscribePromise: Promise<T>,
  timeoutMs: number,
  label: string,
): Promise<{ result: "success"; subscription: T } | { result: "timeout" }> {
  let timeoutHandle!: ReturnType<typeof setTimeout>;
  const timeoutPromise = new Promise<{ result: "timeout" }>((resolve) => {
    timeoutHandle = setTimeout(() => resolve({ result: "timeout" }), timeoutMs);
  });
  const successPromise = subscribePromise.then((subscription) => ({
    result: "success" as const,
    subscription,
  }));

  const race = await Promise.race([successPromise, timeoutPromise]);
  clearTimeout(timeoutHandle);

  if (race.result === "timeout") {
    subscribePromise
      .then((sub) =>
        sub.unsubscribe().catch((err) => {
          log.warn(`Failed to tear down late subscription (${label}):`, err);
        }),
      )
      .catch((err) => {
        log.warn(`Late subscribe rejected after timeout (${label}):`, err);
      });
    return { result: "timeout" };
  }

  return race;
}
