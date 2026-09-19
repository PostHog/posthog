import { parse as parseYaml, stringify as stringifyYaml } from "yaml";
import { z } from "zod";

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
  title: string;
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
  dueDate: string | null;
}

export type GoalMeasure =
  | {
      kind: "hogql";
      sql: string;
      trendSql?: string;
    }
  | { kind: "insight"; shortId: string; url: string; name: string };

export type GoalPeriod = "day" | "week" | "month";

export interface ContextGoal {
  id: string;
  name: string;
  measure: GoalMeasure | null;
  target: GoalTarget | null;
  primary: boolean;
  period?: GoalPeriod;
  percent?: boolean;
  task?: string;
}

export interface BrokenBlock {
  key: "goals" | "reading" | "watching";
  lines: string[];
  error: string;
}

export interface ContextDocument {
  frontmatter: string;
  knowledge: string;
  links: ContextLink[];
  objects: ContextObject[];
  goals: ContextGoal[];
  broken: BrokenBlock[];
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
  url: z.string().refine(isHttpUrl, "Must be an http(s) URL"),
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
  id: z.string().default(() => crypto.randomUUID()),
  name: z.string(),
  primary: z.boolean().default(false),
  target: targetSchema.nullable().default(null),
  measure: measureSchema.nullable().default(null),
  period: z.enum(["day", "week", "month"]).optional(),
  percent: z.boolean().optional(),
  task: z.string().optional(),
});

const FRONTMATTER = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/;
const KEY_LINE = /^([A-Za-z_][\w-]*):/;
const OWN_KEYS = ["goals", "reading", "watching"] as const;
type OwnKey = (typeof OWN_KEYS)[number];

function splitFrontmatter(markdown: string): {
  blocks: Partial<Record<OwnKey, string[]>>;
  rest: string;
  body: string;
} {
  const match = FRONTMATTER.exec(markdown);
  if (!match) return { blocks: {}, rest: "", body: markdown };
  const blocks: Partial<Record<OwnKey, string[]>> = {};
  const rest: string[] = [];
  let current = rest;
  for (const line of match[1].split(/\r?\n/)) {
    const key = KEY_LINE.exec(line)?.[1];
    const own = OWN_KEYS.find((candidate) => candidate === key);
    if (own) {
      current = [];
      blocks[own] = current;
    } else if (key) {
      current = rest;
    }
    current.push(line);
  }
  return {
    blocks,
    rest: rest.join("\n").trim(),
    body: markdown.slice(match[0].length),
  };
}

function readList<T>(
  key: OwnKey,
  lines: string[] | undefined,
  schema: z.ZodType<T>,
): { items: T[]; broken: BrokenBlock | null } {
  if (!lines) return { items: [], broken: null };
  const block = z.object({ [key]: z.array(schema).nullish() });
  try {
    const result = block.safeParse(parseYaml(lines.join("\n")));
    if (result.success) return { items: result.data[key] ?? [], broken: null };
    return {
      items: [],
      broken: { key, lines, error: z.prettifyError(result.error) },
    };
  } catch (cause) {
    const error = cause instanceof Error ? cause.message : String(cause);
    return { items: [], broken: { key, lines, error } };
  }
}

export function parseContextDocument(markdown: string): ContextDocument {
  const { blocks, rest, body } = splitFrontmatter(markdown);
  const goals = readList("goals", blocks.goals, goalSchema);
  const links = readList("reading", blocks.reading, linkSchema);
  const objects = readList("watching", blocks.watching, objectSchema);
  return {
    frontmatter: rest,
    knowledge: body.trim(),
    goals: goals.items,
    links: links.items,
    objects: objects.items,
    broken: [goals.broken, links.broken, objects.broken].filter(
      (block): block is BrokenBlock => block !== null,
    ),
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
    id: goal.id,
    name: goal.name,
    primary: goal.primary || undefined,
    period: goal.period,
    percent: goal.percent || undefined,
    task: goal.measure ? undefined : goal.task,
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
  const kept = doc.broken.map((block) => block.lines.join("\n").trimEnd());
  const front = [doc.frontmatter.trim(), ownYaml, ...kept]
    .filter(Boolean)
    .join("\n");
  const body = doc.knowledge.trim();
  if (!front) return body ? `${body}\n` : "";
  return body ? `---\n${front}\n---\n\n${body}\n` : `---\n${front}\n---\n`;
}

export function formatNumber(value: number): string {
  if (Number.isInteger(value)) return value.toLocaleString("en-US");
  return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
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

export function decodeUrlSegment(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

export function parsePostHogObjectUrl(
  url: string,
  host: string | null,
): { kind: ContextObjectKind; id: string; path: string } | null {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (parsed.host !== host) return null;
  const path = parsed.pathname.replace(/^\/project\/\d+/, "");
  for (const rule of OBJECT_PATH_RULES) {
    const match = rule.re.exec(path);
    if (match) {
      return {
        kind: rule.kind,
        id: decodeUrlSegment(match[1]),
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

export function firstNumericCell(results: unknown[][]): number | null {
  for (const cell of results[0] ?? []) {
    const value = numericCell(cell);
    if (value !== null) return value;
  }
  return null;
}
