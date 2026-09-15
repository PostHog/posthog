// A space's CONTEXT.md is one markdown document, but the Context page edits it
// as four parts: free-form knowledge, files and links, PostHog objects, and
// goals. The parts live in three managed `##` sections with a fixed shape so
// they round-trip through this module; everything else is the knowledge body
// and is carried verbatim. Agents read the whole document as before.

export type ContextObjectKind =
  | "insight"
  | "dashboard"
  | "flag"
  | "experiment"
  | "survey"
  | "error"
  | "replay"
  | "notebook"
  | "cohort"
  | "action"
  | "person"
  | "event"
  | "link";

export interface ContextLink {
  /** Display name. For a bare path, the path itself. */
  title: string;
  /** A URL, or a repository path when the entry is a file. */
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

export interface ContextGoal {
  name: string;
  /** Why this goal matters, in markdown. */
  why: string;
  /** HogQL that returns the current value in its first cell. */
  sql: string;
  target: GoalTarget | null;
}

export interface ContextDocument {
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

const SECTION_LINKS = "Files and links";
const SECTION_OBJECTS = "PostHog objects";
const SECTION_GOALS = "Goals";

type ManagedSection = "links" | "objects" | "goals";

const SECTION_BY_HEADING: Record<string, ManagedSection> = {
  "files and links": "links",
  links: "links",
  files: "links",
  "posthog objects": "objects",
  objects: "objects",
  goals: "goals",
  "goals and measures": "goals",
};

export function emptyContextDocument(): ContextDocument {
  return { knowledge: "", links: [], objects: [], goals: [] };
}

function managedSectionFor(line: string): ManagedSection | null {
  const match = /^##\s+(.+?)\s*$/.exec(line);
  if (!match) return null;
  return SECTION_BY_HEADING[match[1].toLowerCase()] ?? null;
}

// `- [Title](target) — note`, `- kind: [Title](url)`, or `- path — note`.
const BULLET_RE = /^\s*[-*]\s+(.*)$/;
const LINKED_RE =
  /^(?:([\w][\w ]*?):\s+)?\[([^\]]*)\]\(([^)\s]+)\)\s*(?:[—–-]\s*(.*))?$/;
const BARE_RE = /^(\S+)\s*(?:[—–-]\s*(.*))?$/;

function parseLinkBullet(body: string): ContextLink | null {
  const linked = LINKED_RE.exec(body);
  if (linked) {
    return {
      title: linked[2].trim() || linked[3],
      target: linked[3],
      note: (linked[4] ?? "").trim(),
    };
  }
  const bare = BARE_RE.exec(body);
  if (bare) {
    return { title: bare[1], target: bare[1], note: (bare[2] ?? "").trim() };
  }
  return null;
}

function parseObjectBullet(body: string): ContextObject | null {
  const linked = LINKED_RE.exec(body);
  if (!linked) return null;
  const url = linked[3];
  const declared = kindFromLabel(linked[1]);
  const kind = declared ?? parsePostHogObjectUrl(url)?.kind ?? "link";
  return { kind, title: linked[2].trim() || url, url };
}

function kindFromLabel(label: string | undefined): ContextObjectKind | null {
  if (!label) return null;
  const wanted = label.trim().toLowerCase();
  for (const [kind, text] of Object.entries(CONTEXT_OBJECT_KIND_LABELS)) {
    if (kind === wanted || text.toLowerCase() === wanted) {
      return kind as ContextObjectKind;
    }
  }
  if (wanted === "feature flag" || wanted === "feature_flag") return "flag";
  return null;
}

const TARGET_RE =
  /^(?:[-*]\s+)?target:\s*(at least|at most|≥|≤|>=|<=|min|max)?\s*(-?[\d][\d,]*(?:\.\d+)?)\s*%?\s*(?:by\s+(\d{4}-\d{2}-\d{2}))?\s*$/i;

function parseTargetLine(line: string): GoalTarget | null {
  const match = TARGET_RE.exec(line.trim());
  if (!match) return null;
  const word = (match[1] ?? "at least").toLowerCase();
  const direction: GoalDirection =
    word === "at most" || word === "≤" || word === "<=" || word === "max"
      ? "at_most"
      : "at_least";
  const value = Number(match[2].replace(/,/g, ""));
  if (!Number.isFinite(value)) return null;
  return { direction, value, dueDate: match[3] ?? null };
}

function parseGoals(lines: string[]): ContextGoal[] {
  const goals: ContextGoal[] = [];
  let current: ContextGoal | null = null;
  let inSql = false;
  const sqlLines: string[] = [];
  const whyLines: string[] = [];

  const flush = () => {
    if (!current) return;
    current.why = whyLines.join("\n").trim();
    current.sql = current.sql || sqlLines.join("\n").trim();
    goals.push(current);
    current = null;
    sqlLines.length = 0;
    whyLines.length = 0;
  };

  for (const line of lines) {
    if (inSql) {
      if (/^\s*```/.test(line)) {
        inSql = false;
        continue;
      }
      sqlLines.push(line);
      continue;
    }
    const heading = /^###\s+(.+?)\s*$/.exec(line);
    if (heading) {
      flush();
      current = { name: heading[1], why: "", sql: "", target: null };
      continue;
    }
    if (!current) continue;
    if (/^\s*```(sql|hogql)?\s*$/i.test(line)) {
      inSql = true;
      continue;
    }
    const target = parseTargetLine(line);
    if (target) {
      current.target = target;
      continue;
    }
    whyLines.push(line);
  }
  flush();
  return goals;
}

export function parseContextDocument(markdown: string): ContextDocument {
  const doc = emptyContextDocument();
  const knowledge: string[] = [];
  const buckets: Record<ManagedSection, string[]> = {
    links: [],
    objects: [],
    goals: [],
  };
  let section: ManagedSection | null = null;
  let inFence = false;

  for (const line of markdown.split(/\r?\n/)) {
    // A fenced block never ends a section, so a ```sql block inside a goal
    // that happens to contain `## ` stays with the goal.
    if (/^\s*```/.test(line)) inFence = !inFence;
    if (!inFence && /^#{1,2}\s/.test(line)) {
      section = managedSectionFor(line);
      if (section) continue;
    }
    if (section) {
      buckets[section].push(line);
    } else {
      knowledge.push(line);
    }
  }

  doc.knowledge = knowledge.join("\n").trim();
  const stray: string[] = [];

  for (const line of buckets.links) {
    const bullet = BULLET_RE.exec(line);
    const link = bullet ? parseLinkBullet(bullet[1].trim()) : null;
    if (link) doc.links.push(link);
    else if (line.trim()) stray.push(line);
  }
  for (const line of buckets.objects) {
    const bullet = BULLET_RE.exec(line);
    const object = bullet ? parseObjectBullet(bullet[1].trim()) : null;
    if (object) doc.objects.push(object);
    else if (line.trim()) stray.push(line);
  }
  doc.goals = parseGoals(buckets.goals);

  // Prose that sat inside a managed section but is not an entry is kept with
  // the knowledge body rather than lost on the next structured save.
  if (stray.length > 0) {
    doc.knowledge = [doc.knowledge, stray.join("\n").trim()]
      .filter(Boolean)
      .join("\n\n");
  }
  return doc;
}

function formatTarget(target: GoalTarget): string {
  const word = target.direction === "at_most" ? "at most" : "at least";
  const due = target.dueDate ? ` by ${target.dueDate}` : "";
  return `- Target: ${word} ${formatNumber(target.value)}${due}`;
}

export function formatNumber(value: number): string {
  if (Number.isInteger(value)) return value.toLocaleString("en-US");
  return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

export function serializeContextDocument(doc: ContextDocument): string {
  const parts: string[] = [];
  if (doc.knowledge.trim()) parts.push(doc.knowledge.trim());

  if (doc.links.length > 0) {
    const lines = doc.links.map((link) => {
      const note = link.note.trim() ? ` — ${link.note.trim()}` : "";
      const isUrl = /^[a-z][a-z0-9+.-]*:\/\//i.test(link.target);
      return isUrl || link.title !== link.target
        ? `- [${link.title}](${link.target})${note}`
        : `- ${link.target}${note}`;
    });
    parts.push(`## ${SECTION_LINKS}\n\n${lines.join("\n")}`);
  }

  if (doc.objects.length > 0) {
    const lines = doc.objects.map(
      (object) => `- ${object.kind}: [${object.title}](${object.url})`,
    );
    parts.push(`## ${SECTION_OBJECTS}\n\n${lines.join("\n")}`);
  }

  if (doc.goals.length > 0) {
    const blocks = doc.goals.map((goal) => {
      const lines = [`### ${goal.name}`];
      if (goal.why.trim()) lines.push("", goal.why.trim());
      if (goal.target) lines.push("", formatTarget(goal.target));
      if (goal.sql.trim()) lines.push("", "```sql", goal.sql.trim(), "```");
      return lines.join("\n");
    });
    parts.push(`## ${SECTION_GOALS}\n\n${blocks.join("\n\n")}`);
  }

  return parts.length > 0 ? `${parts.join("\n\n")}\n` : "";
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

/** Reads the object kind and id out of a PostHog app URL, or null when the URL points elsewhere. */
export function parsePostHogObjectUrl(
  url: string,
): { kind: ContextObjectKind; id: string } | null {
  let pathname: string;
  try {
    pathname = new URL(url).pathname;
  } catch {
    return null;
  }
  const path = pathname.replace(/^\/project\/\d+/, "");
  for (const rule of OBJECT_PATH_RULES) {
    const match = rule.re.exec(path);
    if (match) return { kind: rule.kind, id: decodeURIComponent(match[1]) };
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

/** The first numeric cell of a HogQL result grid, or null when there is none. */
export function firstNumericCell(results: unknown[][]): number | null {
  const row = results[0];
  if (!row) return null;
  for (const cell of row) {
    if (typeof cell === "number" && Number.isFinite(cell)) return cell;
    if (typeof cell === "string" && cell.trim() !== "") {
      const parsed = Number(cell);
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  return null;
}
