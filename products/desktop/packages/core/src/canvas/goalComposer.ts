import type { GoalDirection, GoalTarget } from "./contextDocument";

/** A query pasted into the composer, as opposed to a sentence about a goal. */
export function looksLikeHogQL(text: string): boolean {
  return /^\s*(select|with)\b/i.test(text);
}

const AT_LEAST_WORDS =
  /\b(at least|more than|over|above|exceed(?:s|ing)?|reach(?:es|ing)?|hit(?:s|ting)?|to|≥|>=)\s*/i;
const AT_MOST_WORDS = /\b(at most|less than|under|below|no more than|≤|<=)\s*/i;
const NUMBER = /(-?\d[\d,]*(?:\.\d+)?)\s*(%|k|m)?/i;
const BY_DATE = /\bby\s+(.+?)\s*$/i;

const MONTHS = [
  "january",
  "february",
  "march",
  "april",
  "may",
  "june",
  "july",
  "august",
  "september",
  "october",
  "november",
  "december",
];

function isoDate(year: number, monthIndex: number, day: number): string {
  const month = String(monthIndex + 1).padStart(2, "0");
  return `${year}-${month}-${String(day).padStart(2, "0")}`;
}

function lastDay(year: number, monthIndex: number): number {
  return new Date(year, monthIndex + 1, 0).getDate();
}

/**
 * Reads a due date from words like "December", "end of Q4", "Mar 15", or an
 * ISO date. A month already past this year means next year.
 */
export function parseDueDate(text: string, now = new Date()): string | null {
  const trimmed = text
    .trim()
    .toLowerCase()
    .replace(/^(the\s+)?end of\s+/, "");
  const iso = /^(\d{4})-(\d{2})-(\d{2})$/.exec(trimmed);
  if (iso) return trimmed;

  const quarter = /^q([1-4])(?:\s+(\d{4}))?$/.exec(trimmed);
  if (quarter) {
    const q = Number(quarter[1]);
    const year = quarter[2] ? Number(quarter[2]) : now.getFullYear();
    const monthIndex = q * 3 - 1;
    return isoDate(year, monthIndex, lastDay(year, monthIndex));
  }

  if (trimmed === "year" || trimmed === "the year" || trimmed === "eoy") {
    return isoDate(now.getFullYear(), 11, 31);
  }
  if (trimmed === "month" || trimmed === "eom") {
    return isoDate(
      now.getFullYear(),
      now.getMonth(),
      lastDay(now.getFullYear(), now.getMonth()),
    );
  }

  const monthDay =
    /^([a-z]+)\.?(?:\s+(\d{1,2})(?:st|nd|rd|th)?)?(?:,?\s+(\d{4}))?$/.exec(
      trimmed,
    );
  if (monthDay) {
    const monthIndex = MONTHS.findIndex((m) => m.startsWith(monthDay[1]));
    if (monthIndex >= 0 && monthDay[1].length >= 3) {
      let year = monthDay[3] ? Number(monthDay[3]) : now.getFullYear();
      const day = monthDay[2] ? Number(monthDay[2]) : lastDay(year, monthIndex);
      if (!monthDay[3] && monthIndex < now.getMonth()) year += 1;
      return isoDate(
        year,
        monthIndex,
        Math.min(day, lastDay(year, monthIndex)),
      );
    }
  }
  return null;
}

export interface ParsedGoalSentence {
  /** The sentence with the target and due date removed. */
  name: string;
  target: GoalTarget | null;
}

function parseNumber(match: RegExpMatchArray): number | null {
  const raw = Number(match[1].replace(/,/g, ""));
  if (!Number.isFinite(raw)) return null;
  const unit = (match[2] ?? "").toLowerCase();
  if (unit === "k") return raw * 1_000;
  if (unit === "m") return raw * 1_000_000;
  return raw;
}

/**
 * Splits "Weekly signups above 500 by end of December" into a name, a target,
 * and a due date, so the composer can prefill the target line. Anything it
 * cannot read stays in the name for the person to fix.
 */
export function parseGoalSentence(
  sentence: string,
  now = new Date(),
): ParsedGoalSentence {
  let text = sentence.trim().replace(/\s+/g, " ");
  let dueDate: string | null = null;

  const by = BY_DATE.exec(text);
  if (by) {
    const parsed = parseDueDate(by[1], now);
    if (parsed) {
      dueDate = parsed;
      text = text.slice(0, by.index).trim();
    }
  }

  let direction: GoalDirection | null = null;
  let cut = -1;
  let numberMatch: RegExpMatchArray | null = null;
  for (const [re, dir] of [
    [AT_MOST_WORDS, "at_most"],
    [AT_LEAST_WORDS, "at_least"],
  ] as const) {
    const m = re.exec(text);
    if (!m) continue;
    const after = text.slice(m.index + m[0].length);
    const num = NUMBER.exec(after);
    if (!num || num.index > 3) continue;
    if (cut === -1 || m.index < cut) {
      cut = m.index;
      direction = dir;
      numberMatch = num;
    }
  }

  let target: GoalTarget | null = null;
  if (direction && numberMatch) {
    const value = parseNumber(numberMatch);
    if (value !== null) {
      target = { direction, value, dueDate };
      text = text.slice(0, cut).trim();
    }
  } else if (dueDate) {
    // "by December" with no number still says when; keep it for the line.
    target = null;
  }

  const name = text.replace(/[\s,.;:]+$/, "");
  return { name: name || sentence.trim(), target };
}
