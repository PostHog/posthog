/** A person's own spend limit for model traffic through the gateway. */
export interface UserSpendLimit {
  /** The limit in USD, or null when none is set. */
  limitUsd: number | null;
  /** Length of the accounting window in seconds; null with no limit. */
  windowSeconds: number | null;
  /**
   * The deployment can hold a spend cap. False means a stop line cannot be
   * set at all, so the app offers warning lines only.
   */
  available: boolean;
}

interface UserSpendLimitPayload {
  limit_usd?: string | null;
  window_seconds?: number | null;
  available?: boolean;
}

export function parseUserSpendLimit(payload: unknown): UserSpendLimit {
  const body = (payload ?? {}) as UserSpendLimitPayload;
  let limitUsd: number | null = null;
  if (body.limit_usd != null) {
    limitUsd = Number(body.limit_usd);
    if (!Number.isFinite(limitUsd)) {
      // Coercing a malformed limit to null would show "no limit" while one exists.
      throw new Error(
        "Couldn't read the spend limit from the server response.",
      );
    }
  }
  return {
    limitUsd,
    windowSeconds: body.window_seconds ?? null,
    available: body.available === true,
  };
}
