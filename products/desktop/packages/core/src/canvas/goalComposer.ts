import type { GoalDirection, GoalTarget } from "./contextDocument";

export function looksLikeHogQL(text: string): boolean {
  return /^\s*(select|with)\b/i.test(text);
}

const AT_LEAST_WORDS =
  /\b(at least|more than|over|above|exceed(?:s|ing)?|reach(?:es|ing)?|hit(?:s|ting)?|to|≥|>=)\s*/i;
const AT_MOST_WORDS = /\b(at most|less than|under|below|no more than|≤|<=)\s*/i;
const NUMBER = /(-?\d[\d,]*(?:\.\d+)?)\s*(%|k|m)?/i;
const BY_DATE = /\bby\s+(.+?)\s*$/i;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const QUARTER = /^q([1-4])(?:\s+(\d{4}))?$/;
const MONTH_DAY =
  /^([a-z]+)\.?(?:\s+(\d{1,2})(?:st|nd|rd|th)?)?(?:,?\s+(\d{4}))?$/;

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

function monthEnd(year: number, monthIndex: number): string {
  return isoDate(year, monthIndex, lastDay(year, monthIndex));
}

export function parseDueDate(text: string, now = new Date()): string | null {
  const trimmed = text
    .trim()
    .toLowerCase()
    .replace(/^(the\s+)?end of\s+/, "");
  if (ISO_DATE.test(trimmed)) return trimmed;

  const quarter = QUARTER.exec(trimmed);
  if (quarter) {
    const year = quarter[2] ? Number(quarter[2]) : now.getFullYear();
    return monthEnd(year, Number(quarter[1]) * 3 - 1);
  }
  if (["year", "the year", "eoy"].includes(trimmed)) {
    return isoDate(now.getFullYear(), 11, 31);
  }
  if (["month", "eom"].includes(trimmed)) {
    return monthEnd(now.getFullYear(), now.getMonth());
  }

  const monthDay = MONTH_DAY.exec(trimmed);
  if (!monthDay || monthDay[1].length < 3) return null;
  const monthIndex = MONTHS.findIndex((month) => month.startsWith(monthDay[1]));
  if (monthIndex < 0) return null;
  const explicitYear = monthDay[3] ? Number(monthDay[3]) : null;
  const rollsOver = explicitYear === null && monthIndex < now.getMonth();
  const year = explicitYear ?? now.getFullYear() + (rollsOver ? 1 : 0);
  const day = monthDay[2] ? Number(monthDay[2]) : lastDay(year, monthIndex);
  return isoDate(year, monthIndex, Math.min(day, lastDay(year, monthIndex)));
}

export interface ParsedGoalSentence {
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

interface TargetWords {
  index: number;
  direction: GoalDirection;
  value: number;
}

const TARGET_WORDS: readonly [RegExp, GoalDirection][] = [
  [AT_MOST_WORDS, "at_most"],
  [AT_LEAST_WORDS, "at_least"],
];

function findTargetWords(text: string): TargetWords | null {
  const found = TARGET_WORDS.flatMap(([pattern, direction]) => {
    const words = pattern.exec(text);
    if (!words) return [];
    const number = NUMBER.exec(text.slice(words.index + words[0].length));
    if (!number || number.index > 3) return [];
    const value = parseNumber(number);
    return value === null ? [] : [{ index: words.index, direction, value }];
  });
  return found.sort((a, b) => a.index - b.index)[0] ?? null;
}

export function parseGoalSentence(
  sentence: string,
  now = new Date(),
): ParsedGoalSentence {
  const text = sentence.trim().replace(/\s+/g, " ");
  const by = BY_DATE.exec(text);
  const dueDate = by ? parseDueDate(by[1], now) : null;
  const withoutDate = by && dueDate ? text.slice(0, by.index) : text;
  const target = findTargetWords(withoutDate);
  const rawName = target ? withoutDate.slice(0, target.index) : withoutDate;
  const name = rawName.trim().replace(/[\s,.;:]+$/, "");
  return {
    name: name || text,
    target: target
      ? { direction: target.direction, value: target.value, dueDate }
      : null,
  };
}
