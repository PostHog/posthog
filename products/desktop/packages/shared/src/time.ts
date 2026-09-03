export function formatClockTime(time: string): string {
  const [hour, minute] = time.split(":").map(Number);
  return new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(2000, 0, 1, hour, minute)));
}

/**
 * Format a timestamp as a short relative string (e.g. "3m", "2h", "5d").
 * Accepts either a Unix ms timestamp or an ISO date string.
 */
export function formatRelativeTimeShort(timestamp: number | string): string {
  const ms =
    typeof timestamp === "string" ? new Date(timestamp).getTime() : timestamp;
  const diff = Date.now() - ms;

  const minutes = Math.floor(diff / 60_000);
  const hours = Math.floor(diff / 3_600_000);
  const days = Math.floor(diff / 86_400_000);
  const weeks = Math.floor(days / 7);
  const months = Math.floor(days / 30);
  const years = Math.floor(days / 365);

  if (years > 0) return `${years}y`;
  if (months > 0) return `${months}mo`;
  if (weeks > 0) return `${weeks}w`;
  if (days > 0) return `${days}d`;
  if (hours > 0) return `${hours}h`;
  if (minutes > 0) return `${minutes}m`;
  return "now";
}

/**
 * How long ago something happened, said as a phrase: "2h ago", "3w ago", or
 * "just now" under a minute. The same scale `formatRelativeTimeShort` uses, so
 * a stamp and a phrase for one timestamp cannot disagree.
 */
export function formatRelativeAge(timestamp: number | string): string {
  const short = formatRelativeTimeShort(timestamp);
  return short === "now" ? "just now" : `${short} ago`;
}

/**
 * The exact moment, in the reader's own locale and zone. What a relative age
 * hides, for the tooltip behind it.
 */
export function formatAbsoluteDateTime(timestamp: number | string): string {
  const ms =
    typeof timestamp === "string" ? new Date(timestamp).getTime() : timestamp;
  return new Date(ms).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/**
 * Format a timestamp as a longer relative string (e.g. "3 minutes ago", "1 day ago").
 * Falls back to a locale date for anything older than a week.
 * Accepts either a Unix ms timestamp or an ISO date string.
 */
export function formatRelativeTimeLong(timestamp: number | string): string {
  const date =
    typeof timestamp === "string" ? new Date(timestamp) : new Date(timestamp);
  const diff = Date.now() - date.getTime();

  const seconds = Math.floor(diff / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (seconds < 60) return "just now";
  if (minutes < 60)
    return minutes === 1 ? "1 minute ago" : `${minutes} minutes ago`;
  if (hours < 24) return hours === 1 ? "1 hour ago" : `${hours} hours ago`;
  if (days < 7) return days === 1 ? "1 day ago" : `${days} days ago`;

  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/**
 * Whole local calendar days between `timestamp` and `now` (0 = today,
 * 1 = yesterday, negative = future). Uses local-midnight boundaries so the
 * split lands on the viewer's midnight, not a UTC one.
 */
export function getLocalDayDiff(
  timestamp: number | string | Date,
  now: Date = new Date(),
): number {
  const date = new Date(timestamp);
  const startOfDay = (d: Date) =>
    new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  return Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000);
}

/**
 * Local calendar-day identity, for deciding where a day separator goes. Two
 * timestamps on the same day share a key regardless of time, and the key is
 * built from local getters (not the UTC ISO) so the split lands on the viewer's
 * midnight.
 */
export function getLocalDayKey(timestamp: number | string | Date): string {
  const date = new Date(timestamp);
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

function ordinal(n: number): string {
  const suffix = ["th", "st", "nd", "rd"];
  const rem = n % 100;
  return `${n}${suffix[(rem - 20) % 10] ?? suffix[rem] ?? suffix[0]}`;
}

/**
 * A day separator's label: "Today" / "Yesterday" for the recent days, then a
 * weekday + ordinal ("Monday 5th") within the week, adding the month (and the
 * year when it differs) further back so older separators stay unambiguous.
 *
 * Shared by the space feed and the space sidebar's recents, so the same day is
 * never named two different ways in one window.
 */
export function formatDaySeparatorLabel(
  timestamp: number | string | Date,
  now: Date = new Date(),
): string {
  const date = new Date(timestamp);
  const days = getLocalDayDiff(date, now);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  const weekday = date.toLocaleDateString(undefined, { weekday: "long" });
  const day = ordinal(date.getDate());
  if (days < 7) return `${weekday} ${day}`;
  const month = date.toLocaleDateString(undefined, { month: "long" });
  const year =
    date.getFullYear() === now.getFullYear() ? "" : `, ${date.getFullYear()}`;
  return `${weekday}, ${month} ${day}${year}`;
}

/**
 * The compact form of `formatDaySeparatorLabel`, for a sidebar column with no
 * room for "Wednesday, May 20th": the recent days by name, then a short date.
 *
 * Both read the same `getLocalDayDiff`, so the two can differ in how verbosely
 * they name a day but never in which day a timestamp falls on.
 */
export function formatShortDayLabel(
  timestamp: number | string | Date,
  now: Date = new Date(),
): string {
  const date = new Date(timestamp);
  const days = getLocalDayDiff(date, now);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return date.toLocaleDateString(undefined, { weekday: "long" });
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: date.getFullYear() === now.getFullYear() ? undefined : "numeric",
  });
}

export function getRelativeDateGroup(
  timestamp: number | string,
): string | null {
  const days = getLocalDayDiff(timestamp);
  if (days <= 0) return null;
  if (days === 1) return "Yesterday";
  if (days < 7) return "This week";
  if (days < 30) return "This month";
  return "Earlier";
}
