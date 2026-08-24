/** A person's own spend limit for model traffic through the gateway. */
export interface UserSpendLimit {
  /** The limit in USD, or null when none is set. */
  limitUsd: number | null;
  /** Length of the accounting window in seconds; null with no limit. */
  windowSeconds: number | null;
  /**
   * The gateway can hold spend on this deployment. False means a limit cannot
   * be set at all, so anything the app shows informs only.
   */
  enforced: boolean;
}

interface UserSpendLimitPayload {
  limit_usd?: string | null;
  window_seconds?: number | null;
  enforced?: boolean;
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
    enforced: body.enforced === true,
  };
}
