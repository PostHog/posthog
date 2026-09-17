import { parse as parseYaml, stringify as stringifyYaml } from "yaml";
import { z } from "zod";

// A space's CONTEXT.md keeps its structured parts in the YAML frontmatter:
// `goals`, `reading` (files and links), and `watching` (PostHog objects). The
// body under the frontmatter is prose and is stored as it was written. Other
// frontmatter keys belong to the wiki and travel through untouched.

const OBJECT_KINDS = [
  "insight",
  "dashboard",
  "flag",
  "experiment",
  "survey",
  "error",
  "replay",
  "notebook",
  "cohort",
  "action",
  "person",
  "event",
  "link",
] as const;

export type ContextObjectKind = (typeof OBJECT_KINDS)[number];

export interface ContextLink {
  /** Display name. For a bare path, the path itself. */
  title: string;
  /** A URL, or a wiki path when the entry is a file. */
  target: string;
  note: string;
}

export interface ContextObject {
  kind: ContextObjectKind;
  title: string;
  url: string;
}

export type GoalDirection = "at_least" | "at_most";

export interface GoalTarget {
  direction: GoalDirection;
  value: number;
  /** ISO date (YYYY-MM-DD) the target should be met by. */
  dueDate: string | null;
}

/** How a goal's current value is read. */
export type GoalMeasure =
  | {
      kind: "hogql";
      sql: string;
      /** One row per period, period first and value last; drawn as a sparkline. */
      trendSql?: string;
    }
  | { kind: "insight"; shortId: string; url: string; name: string };

export interface ContextGoal {
  name: string;
  /** Why this goal matters, in markdown. */
  why: string;
  /** Null until a person or an agent adds one. */
  measure: GoalMeasure | null;
  target: GoalTarget | null;
  /** The one goal this space is judged on. At most one per document. */
  primary: boolean;
}

export interface ContextDocument {
  /** The wiki's own frontmatter lines (summary, status, ids), kept as written. */
  frontmatter: string;
  knowledge: string;
  links: ContextLink[];
  objects: ContextObject[];
  goals: ContextGoal[];
}

export const CONTEXT_OBJECT_KIND_LABELS: Record<ContextObjectKind, string> = {
  insight: "Insight",
  dashboard: "Dashboard",
  flag: "Feature flag",
  experiment: "Experiment",
  survey: "Survey",
  error: "Error issue",
  replay: "Replay",
  notebook: "Notebook",
  cohort: "Cohort",
  action: "Action",
  person: "Person",
  event: "Event",
  link: "Link",
};

const linkSchema = z.object({
  title: z.string(),
  target: z.string(),
  note: z.string().default(""),
});

const objectSchema = z.object({
  kind: z.enum(OBJECT_KINDS),
  title: z.string(),
  url: z.string(),
});

const targetSchema = z
  .object({
    direction: z.enum(["at_least", "at_most"]),
    value: z.coerce.number(),
    due_date: z.string().nullable().default(null),
  })
  .transform(
    (target): GoalTarget => ({
      direction: target.direction,
      value: target.value,
      dueDate: target.due_date,
    }),
  );

const measureSchema = z
  .discriminatedUnion("kind", [
    z.object({
      kind: z.literal("hogql"),
      sql: z.string(),
      trend_sql: z.string().optional(),
    }),
    z.object({
      kind: z.literal("insight"),
      short_id: z.string(),
      url: z.string(),
      name: z.string(),
    }),
  ])
  .transform(
    (measure): GoalMeasure =>
      measure.kind === "hogql"
        ? { kind: "hogql", sql: measure.sql, trendSql: measure.trend_sql }
        : {
            kind: "insight",
            shortId: measure.short_id,
            url: measure.url,
            name: measure.name,
          },
  );

const goalSchema = z.object({
  name: z.string(),
  why: z.string().default(""),
  primary: z.boolean().default(false),
  target: targetSchema.nullable().default(null),
  measure: measureSchema.nullable().default(null),
});

const FRONTMATTER = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/;
const KEY_LINE = /^([A-Za-z_][\w-]*):/;
const OWN_KEYS = ["goals", "reading", "watching"] as const;
type OwnKey = (typeof OWN_KEYS)[number];

// The wiki reads its frontmatter line by line, so a `summary:` may hold a
// colon that strict YAML rejects. Only the three list blocks are YAML.
function splitFrontmatter(markdown: string): {
  own: Partial<Record<OwnKey, string>>;
  rest: string;
  body: string;
} {
  const match = FRONTMATTER.exec(markdown);
  if (!match) return { own: {}, rest: "", body: markdown };
  const blocks: Partial<Record<OwnKey, string[]>> = {};
  const rest: string[] = [];
  let current = rest;
  for (const line of match[1].split(/\r?\n/)) {
    const key = KEY_LINE.exec(line)?.[1];
    if (key) {
      const own = OWN_KEYS.find((candidate) => candidate === key);
      current = own ? [] : rest;
      if (own) blocks[own] = current;
    }
    current.push(line);
  }
  const own: Partial<Record<OwnKey, string>> = {};
  for (const key of OWN_KEYS) {
    const lines = blocks[key];
    if (lines) own[key] = lines.join("\n");
  }
  return {
    own,
    rest: rest.join("\n").trim(),
    body: markdown.slice(match[0].length),
  };
}

function readList<T>(
  key: OwnKey,
  block: string | undefined,
  schema: z.ZodType<T>,
): T[] {
  if (block === undefined) return [];
  const data: unknown = parseYaml(block);
  const value =
    data && typeof data === "object" ? Reflect.get(data, key) : undefined;
  if (value === undefined || value === null) return [];
  const result = z.array(schema).safeParse(value);
  if (!result.success) {
    throw new Error(
      `The frontmatter key \`${key}\` is not in the expected shape.\n${z.prettifyError(result.error)}`,
    );
  }
  return result.data;
}

/** Throws when a list block is not YAML or has the wrong shape. */
export function parseContextDocument(markdown: string): ContextDocument {
  const { own, rest, body } = splitFrontmatter(markdown);
  return {
    frontmatter: rest,
    knowledge: body.trim(),
    goals: readList("goals", own.goals, goalSchema),
    links: readList("reading", own.reading, linkSchema),
    objects: readList("watching", own.watching, objectSchema),
  };
}

function writeMeasure(measure: GoalMeasure): Record<string, unknown> {
  if (measure.kind === "insight") {
    return {
      kind: "insight",
      short_id: measure.shortId,
      url: measure.url,
      name: measure.name,
    };
  }
  return {
    kind: "hogql",
    sql: measure.sql.trim(),
    trend_sql: measure.trendSql?.trim() || undefined,
  };
}

function writeGoal(goal: ContextGoal): Record<string, unknown> {
  return {
    name: goal.name,
    why: goal.why.trim() || undefined,
    primary: goal.primary || undefined,
    target: goal.target
      ? {
          direction: goal.target.direction,
          value: goal.target.value,
          due_date: goal.target.dueDate ?? undefined,
        }
      : undefined,
    measure: goal.measure ? writeMeasure(goal.measure) : undefined,
  };
}

export function serializeContextDocument(doc: ContextDocument): string {
  const own: Partial<Record<OwnKey, unknown>> = {};
  if (doc.goals.length > 0) own.goals = doc.goals.map(writeGoal);
  if (doc.links.length > 0) {
    own.reading = doc.links.map((link) => ({
      title: link.title,
      target: link.target,
      note: link.note.trim() || undefined,
    }));
  }
  if (doc.objects.length > 0) {
    own.watching = doc.objects.map((object) => ({
      kind: object.kind,
      title: object.title,
      url: object.url,
    }));
  }
  const ownYaml =
    Object.keys(own).length > 0
      ? stringifyYaml(own, { lineWidth: 0 }).trimEnd()
      : "";
  const front = [doc.frontmatter.trim(), ownYaml].filter(Boolean).join("\n");
  const body = doc.knowledge.trim();
  if (!front) return body ? `${body}\n` : "";
  return body ? `---\n${front}\n---\n\n${body}\n` : `---\n${front}\n---\n`;
}

export function formatNumber(value: number): string {
  if (Number.isInteger(value)) return value.toLocaleString("en-US");
  return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

export function goalValueSuffix(goalName: string): string {
  return /%|percent|conversion/i.test(goalName) ? "%" : "";
}

const OBJECT_PATH_RULES: { kind: ContextObjectKind; re: RegExp }[] = [
  { kind: "insight", re: /^\/insights\/([^/?#]+)/ },
  { kind: "dashboard", re: /^\/dashboard\/(\d+)/ },
  { kind: "flag", re: /^\/feature_flags\/(\d+)/ },
  { kind: "experiment", re: /^\/experiments\/(\d+)/ },
  { kind: "survey", re: /^\/surveys\/([^/?#]+)/ },
  { kind: "error", re: /^\/error_tracking\/([0-9a-f-]{8,})/i },
  { kind: "replay", re: /^\/replay\/([^/?#]+)/ },
  { kind: "notebook", re: /^\/notebooks\/([^/?#]+)/ },
  { kind: "cohort", re: /^\/cohorts\/(\d+)/ },
  { kind: "action", re: /^\/data-management\/actions\/(\d+)/ },
  { kind: "event", re: /^\/data-management\/events\/([^/?#]+)/ },
  { kind: "person", re: /^\/persons?\/([^/?#]+)/ },
];

/**
 * Reads the object kind and id out of a PostHog app URL, or null when the URL
 * points elsewhere. `path` is the object's own path (`/feature_flags/12`),
 * which is how other products' signals refer to it.
 */
export function parsePostHogObjectUrl(
  url: string,
): { kind: ContextObjectKind; id: string; path: string } | null {
  let pathname: string;
  try {
    pathname = new URL(url).pathname;
  } catch {
    return null;
  }
  const path = pathname.replace(/^\/project\/\d+/, "");
  for (const rule of OBJECT_PATH_RULES) {
    const match = rule.re.exec(path);
    if (match) {
      return {
        kind: rule.kind,
        id: decodeURIComponent(match[1]),
        path: match[0],
      };
    }
  }
  return null;
}

export function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

export function urlHost(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export type GoalStatus =
  | "met"
  | "on_track"
  | "behind"
  | "no_target"
  | "unmeasured";

/** How a measured value stands against the goal's target. */
export function goalStatus(
  current: number | null,
  target: GoalTarget | null,
): GoalStatus {
  if (!target) return "no_target";
  if (current === null) return "unmeasured";
  const met =
    target.direction === "at_most"
      ? current <= target.value
      : current >= target.value;
  if (met) return "met";
  return goalProgress(current, target) >= 0.7 ? "on_track" : "behind";
}

/** 0..1 progress toward the target. An "at most" goal is full when the value sits under the cap. */
export function goalProgress(current: number, target: GoalTarget): number {
  if (target.direction === "at_most") {
    if (current <= target.value) return 1;
    if (current <= 0) return 0;
    return Math.max(0, Math.min(1, target.value / current));
  }
  if (target.value <= 0) return current >= target.value ? 1 : 0;
  return Math.max(0, Math.min(1, current / target.value));
}

export function numericCell(cell: unknown): number | null {
  if (typeof cell === "number") return Number.isFinite(cell) ? cell : null;
  if (typeof cell === "string" && cell.trim() !== "") {
    const parsed = Number(cell);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

/** The first numeric cell of a HogQL result grid, or null when there is none. */
export function firstNumericCell(results: unknown[][]): number | null {
  for (const cell of results[0] ?? []) {
    const value = numericCell(cell);
    if (value !== null) return value;
  }
  return null;
}
