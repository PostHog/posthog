/** Above this, the badge reads "99+" so a long numeral can't stretch the tile. */
const MAX_DOCK_BADGE_COUNT = 99;

/**
 * The badge label for a count, where "" clears it.
 *
 * The count arrives from the renderer over tRPC, so it is only trustworthy as
 * far as the zod schema: a fractional or non-finite value must render as
 * something sane rather than reaching `setBadge` as "NaN".
 */
export function formatDockBadge(count: number): string {
  if (!Number.isFinite(count)) return "";
  const whole = Math.floor(count);
  if (whole <= 0) return "";
  return whole > MAX_DOCK_BADGE_COUNT ? `${MAX_DOCK_BADGE_COUNT}+` : `${whole}`;
}
