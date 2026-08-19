import type { TaskRunStatus } from "@posthog/shared/domain-types";

/**
 * GitHub-style query language for custom task feeds.
 *
 * A query is whitespace-separated chunks. A chunk shaped `key:value` with a
 * known key is a filter token; everything else is free text, searched over
 * task title, description, and number. Semantics follow GitHub search:
 *
 * - the same key repeated is OR (`created-by:a created-by:b` — either author),
 * - different keys are AND,
 * - `-key:value` negates, and `key:not:value` is accepted as an alias,
 * - double quotes carry spaces (`space:"desktop app"`).
 *
 * Unknown keys deliberately fall through to free text rather than erroring —
 * a URL's `https:` or a stray `re:` in pasted text must not break the query.
 * The autocomplete is what steers people onto real keys.
 */

/** Canonical filter keys. Aliases (`author:`, `channel:`, …) map onto these. */
export type FeedQueryKey =
  | "created-by"
  | "space"
  | "repo"
  | "status"
  | "origin"
  | "is"
  | "pr"
  | "ci"
  | "type";

const KEY_ALIASES: Record<string, FeedQueryKey> = {
  "created-by": "created-by",
  author: "created-by",
  by: "created-by",
  space: "space",
  channel: "space",
  repo: "repo",
  repository: "repo",
  status: "status",
  origin: "origin",
  is: "is",
  pr: "pr",
  ci: "ci",
  type: "type",
};

export const TASK_RUN_STATUSES: readonly TaskRunStatus[] = [
  "not_started",
  "queued",
  "in_progress",
  "completed",
  "failed",
  "cancelled",
];

/** Friendlier spellings people will type before they learn the enum. */
const STATUS_ALIASES: Record<string, TaskRunStatus> = {
  running: "in_progress",
  done: "completed",
};

/** `is:` sugar that expands to a run-status token. */
const IS_STATUS_SUGAR: Record<string, TaskRunStatus> = {
  running: "in_progress",
  done: "completed",
  failed: "failed",
};

export const PR_VALUES = [
  "any",
  "none",
  "open",
  "draft",
  "merged",
  "closed",
] as const;
export type PrValue = (typeof PR_VALUES)[number];

/** PR states the task payload can answer today (a PR exists or it doesn't).
 * The rest need the indexed PR/CI state the backend doesn't persist yet. */
const SUPPORTED_PR_VALUES: ReadonlySet<string> = new Set(["any", "none"]);

export const CI_VALUES = [
  "red",
  "failing",
  "green",
  "passing",
  "pending",
] as const;

export interface FeedQueryToken {
  /** The chunk as typed, for chips and error messages. */
  raw: string;
  key: FeedQueryKey;
  value: string;
  negated: boolean;
}

export type FeedQueryIssueKind = "unknown-value" | "unsupported";

export interface FeedQueryIssue {
  /** The chunk or value the issue is about. */
  raw: string;
  kind: FeedQueryIssueKind;
  message: string;
}

export interface ParsedFeedQuery {
  /** Free-text words, joined, for the server's substring search. */
  text: string;
  tokens: FeedQueryToken[];
  issues: FeedQueryIssue[];
}

// Chunks: runs of non-space characters, where a double-quoted span may carry
// spaces mid-chunk (`space:"desktop app"` is one chunk).
const CHUNK_RE = /(?:[^\s"]+|"[^"]*")+/g;
const TOKEN_RE = /^(-)?([A-Za-z][A-Za-z-]*):(.*)$/;

function unquote(value: string): string {
  return value.replace(/"([^"]*)"/g, "$1");
}

export function parseFeedQuery(query: string): ParsedFeedQuery {
  const words: string[] = [];
  const tokens: FeedQueryToken[] = [];
  const issues: FeedQueryIssue[] = [];

  for (const raw of query.match(CHUNK_RE) ?? []) {
    const match = TOKEN_RE.exec(raw);
    const key = match ? KEY_ALIASES[match[2].toLowerCase()] : undefined;
    if (!match || !key) {
      words.push(unquote(raw));
      continue;
    }
    let negated = match[1] === "-";
    let value = unquote(match[3]);
    if (value.toLowerCase().startsWith("not:")) {
      negated = true;
      value = value.slice("not:".length);
    }
    if (value === "") {
      // A dangling `status:` is someone mid-typing, not a filter for the empty
      // string — drop it rather than matching nothing.
      continue;
    }
    tokens.push({ raw, key, value, negated });
    validateToken({ raw, key, value, negated }, issues);
  }

  return { text: words.join(" "), tokens, issues };
}

function validateToken(token: FeedQueryToken, issues: FeedQueryIssue[]): void {
  const value = token.value.toLowerCase();
  switch (token.key) {
    case "status": {
      if (
        !STATUS_ALIASES[value] &&
        !TASK_RUN_STATUSES.includes(value as TaskRunStatus)
      ) {
        issues.push({
          raw: token.raw,
          kind: "unknown-value",
          message: `Unknown status "${token.value}". Expected one of: ${TASK_RUN_STATUSES.join(", ")}`,
        });
      }
      return;
    }
    case "is": {
      if (value !== "archived" && !IS_STATUS_SUGAR[value]) {
        issues.push({
          raw: token.raw,
          kind: "unknown-value",
          message: `Unknown "is:" value "${token.value}". Expected one of: archived, running, done, failed`,
        });
      }
      return;
    }
    case "pr": {
      if (!PR_VALUES.includes(value as PrValue)) {
        issues.push({
          raw: token.raw,
          kind: "unknown-value",
          message: `Unknown "pr:" value "${token.value}". Expected one of: ${PR_VALUES.join(", ")}`,
        });
        return;
      }
      if (!SUPPORTED_PR_VALUES.has(value)) {
        issues.push({
          raw: token.raw,
          kind: "unsupported",
          message: `"pr:${value}" isn't available yet, so it is ignored for now`,
        });
      }
      return;
    }
    case "ci": {
      if (!CI_VALUES.includes(value as (typeof CI_VALUES)[number])) {
        issues.push({
          raw: token.raw,
          kind: "unknown-value",
          message: `Unknown "ci:" value "${token.value}". Expected one of: ${CI_VALUES.join(", ")}`,
        });
        return;
      }
      issues.push({
        raw: token.raw,
        kind: "unsupported",
        message: `"ci:${value}" isn't available yet, so it is ignored for now`,
      });
      return;
    }
    case "type": {
      if (value !== "task") {
        issues.push({
          raw: token.raw,
          kind: "unknown-value",
          message: `Feeds only carry tasks today, so "type:${token.value}" matches nothing`,
        });
      }
      return;
    }
    default:
      return;
  }
}

/**
 * One visual segment of a query string, in order and covering it exactly —
 * `segments.map(s => s.raw).join("")` reproduces the input. This is what the
 * editor's inline highlighter and the feed page's read-only rendering draw,
 * so both surfaces color the query the same way.
 */
export interface FeedQuerySegment {
  raw: string;
  kind: "whitespace" | "text" | "token";
  token?: {
    key: FeedQueryKey;
    value: string;
    negated: boolean;
    /** The parser flagged this token's value. */
    invalid: boolean;
    /** Valid, but nothing can act on it yet (pr states, ci). */
    unsupported: boolean;
  };
}

export function lexFeedQuery(query: string): FeedQuerySegment[] {
  const segments: FeedQuerySegment[] = [];
  let cursor = 0;
  for (const match of query.matchAll(CHUNK_RE)) {
    const start = match.index;
    if (start > cursor) {
      segments.push({ raw: query.slice(cursor, start), kind: "whitespace" });
    }
    const raw = match[0];
    cursor = start + raw.length;

    const tokenMatch = TOKEN_RE.exec(raw);
    const key = tokenMatch
      ? KEY_ALIASES[tokenMatch[2].toLowerCase()]
      : undefined;
    if (!tokenMatch || !key || tokenMatch[3] === "") {
      segments.push({ raw, kind: "text" });
      continue;
    }
    let negated = tokenMatch[1] === "-";
    let value = unquote(tokenMatch[3]);
    if (value.toLowerCase().startsWith("not:")) {
      negated = true;
      value = value.slice("not:".length);
    }
    const issues: FeedQueryIssue[] = [];
    validateToken({ raw, key, value, negated }, issues);
    segments.push({
      raw,
      kind: "token",
      token: {
        key,
        value,
        negated,
        invalid: issues.some((issue) => issue.kind === "unknown-value"),
        unsupported: issues.some((issue) => issue.kind === "unsupported"),
      },
    });
  }
  if (cursor < query.length) {
    segments.push({ raw: query.slice(cursor), kind: "whitespace" });
  }
  return segments;
}

/** The structural slice of a member the planner needs (a `UserBasic` fits). */
export interface FeedQueryMember {
  id: number;
  uuid: string;
  email: string;
  first_name?: string;
  last_name?: string;
}

export interface FeedQuerySpace {
  id: string;
  name: string;
}

/** Everything name resolution needs; the UI layer supplies live data. */
export interface FeedQueryPlanContext {
  members: readonly FeedQueryMember[];
  spaces: readonly FeedQuerySpace[];
  me?: FeedQueryMember | null;
}

/** The tasks-list request parameters a query compiles down to. */
export interface FeedQueryServerParams {
  search?: string;
  createdBy?: number;
  channel?: string;
  repository?: string;
  status?: TaskRunStatus;
  originProduct?: string;
  archived?: boolean;
}

/** The structural slice of a task the client-side predicate reads. */
export interface FeedQueryTask {
  created_by?: { uuid: string } | null;
  channel?: string | null;
  repository?: string | null;
  origin_product?: string;
  latest_run?: {
    status: TaskRunStatus;
    output?: Record<string, unknown> | null;
  } | null;
}

export interface FeedQueryPlan {
  /**
   * The tasks-list requests to run and union. Usually one; an OR group
   * (`created-by:a created-by:b`) fans out into one request per value, so
   * each side is fetched with its own indexed filter rather than hoping both
   * authors appear in one unfiltered recent page.
   */
  requests: FeedQueryServerParams[];
  /** Covers what the server params can't: negation, OR groups, PR presence. */
  matches: (task: FeedQueryTask) => boolean;
  /** Parser issues plus resolution issues (no teammate/space by that name). */
  issues: FeedQueryIssue[];
}

function normalize(value: string): string {
  return value.trim().toLowerCase();
}

const MAX_SUGGESTED_NAME_LENGTH = 80;

/** Friendlier words for the run-status enum, for suggested feed names. */
const STATUS_WORDS: Partial<Record<string, string>> = {
  in_progress: "running",
  completed: "done",
  not_started: "not started",
};

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

/**
 * A readable name for a feed, derived from its query — what the create modal
 * pre-fills so naming a feed costs nothing. `created-by:@me pr:any` suggests
 * "My tasks with a PR"; `billing status:failed` suggests "Failed billing
 * tasks". Best-effort phrasing: it only has to be a decent default, the field
 * stays editable.
 */
export function suggestFeedName(query: string): string {
  const parsed = parseFeedQuery(query);
  const positives = (key: FeedQueryKey) =>
    parsed.tokens.filter((t) => t.key === key && !t.negated);

  const authors = positives("created-by").map((t) => normalize(t.value));
  const uniqueAuthors = [...new Set(authors)];
  let possessive = "";
  if (
    uniqueAuthors.length === 1 &&
    (uniqueAuthors[0] === "@me" || uniqueAuthors[0] === "me")
  ) {
    possessive = "my";
  } else if (uniqueAuthors.length > 0) {
    const names = uniqueAuthors.map((a) =>
      a === "@me" || a === "me" ? "my" : capitalize(a),
    );
    possessive = `${names.join(" & ")}'s`;
  }

  const statusValues = [
    ...positives("status").map((t) => {
      const value = normalize(t.value);
      return STATUS_ALIASES[value] ?? value;
    }),
    ...positives("is")
      .map((t) => IS_STATUS_SUGAR[normalize(t.value)])
      .filter((v): v is TaskRunStatus => !!v),
  ];
  const statusWords = [...new Set(statusValues)].map(
    (value) => STATUS_WORDS[value] ?? value,
  );

  const archived = positives("is").some(
    (t) => normalize(t.value) === "archived",
  );
  const repos = positives("repo").map((t) => t.value);
  const spaces = positives("space").map((t) => t.value.replace(/^#/, ""));
  const prValue = positives("pr")
    .map((t) => normalize(t.value))
    .find((v) => v === "any" || v === "none");

  const head = [
    possessive,
    archived ? "archived" : "",
    statusWords.join(" or "),
    parsed.text,
  ]
    .filter(Boolean)
    .join(" ");
  const places = [...spaces, ...repos];
  const tail = [
    places.length > 0 ? `in ${places.join(" or ")}` : "",
    prValue === "any" ? "with a PR" : prValue === "none" ? "without a PR" : "",
  ]
    .filter(Boolean)
    .join(" ");

  const name = [head, "tasks", tail].filter(Boolean).join(" ").trim();
  if (name === "tasks") return "";
  return capitalize(name).slice(0, MAX_SUGGESTED_NAME_LENGTH);
}

function memberMatches(member: FeedQueryMember, value: string): boolean {
  const needle = normalize(value);
  const first = normalize(member.first_name ?? "");
  const last = normalize(member.last_name ?? "");
  const full = `${first} ${last}`.trim();
  const email = normalize(member.email);
  const emailUser = email.split("@")[0];
  return (
    first.startsWith(needle) ||
    last.startsWith(needle) ||
    full.startsWith(needle) ||
    email === needle ||
    emailUser === needle
  );
}

interface Group {
  positives: FeedQueryToken[];
  negatives: FeedQueryToken[];
}

function groupOf(map: Map<string, Group>, key: string): Group {
  let group = map.get(key);
  if (!group) {
    group = { positives: [], negatives: [] };
    map.set(key, group);
  }
  return group;
}

const MATCH_ALL = () => true;
const MATCH_NONE = () => false;

/**
 * How many list requests one query may fan out into. An OR group that would
 * push past this stays client-side only — its predicate still filters, but
 * over the base request's page rather than per-value requests.
 */
const MAX_PLAN_REQUESTS = 8;

/**
 * Compile a parsed query into tasks-list requests plus a client predicate.
 *
 * A key with exactly one positive value and no negations rides the base
 * request (indexed, cheap). A key repeated (OR) fans out into one request per
 * value — filtering the OR client-side over a single unfiltered page silently
 * dropped every match older than that page. Negations and PR presence still
 * filter the fetched pages client-side, which is honest at today's page size.
 */
export function planFeedQuery(
  parsed: ParsedFeedQuery,
  context: FeedQueryPlanContext,
): FeedQueryPlan {
  const server: FeedQueryServerParams = {};
  // Each entry is one OR group's per-value request params; the cartesian
  // product with the base params becomes the request list.
  const fanouts: Partial<FeedQueryServerParams>[][] = [];
  const predicates: ((task: FeedQueryTask) => boolean)[] = [];
  const issues: FeedQueryIssue[] = [...parsed.issues];

  if (parsed.text) server.search = parsed.text;

  // Fold `is:` sugar and aliases into canonical groups first, so
  // `is:failed status:failed` lands in one OR group rather than two ANDed ones.
  const groups = new Map<string, Group>();
  for (const token of parsed.tokens) {
    let key: string = token.key;
    let value = token.value;
    if (token.key === "is") {
      const sugar = IS_STATUS_SUGAR[normalize(token.value)];
      if (sugar) {
        key = "status";
        value = sugar;
      } else if (normalize(token.value) === "archived") {
        key = "archived";
        value = "archived";
      } else {
        continue; // flagged by the parser already
      }
    }
    if (key === "status") {
      value = STATUS_ALIASES[normalize(value)] ?? normalize(value);
      if (!TASK_RUN_STATUSES.includes(value as TaskRunStatus)) continue;
    }
    const group = groupOf(groups, key);
    (token.negated ? group.negatives : group.positives).push({
      ...token,
      value,
    });
  }

  const createdBy = groups.get("created-by");
  if (createdBy) {
    const resolve = (token: FeedQueryToken): FeedQueryMember[] => {
      const value = normalize(token.value);
      if (value === "@me" || value === "me") {
        return context.me ? [context.me] : [];
      }
      const matched = context.members.filter((m) => memberMatches(m, value));
      if (matched.length === 0) {
        issues.push({
          raw: token.raw,
          kind: "unknown-value",
          message: `No teammate matches "${token.value}"`,
        });
      }
      return matched;
    };
    // Unique members across all positive tokens: two spellings of one person
    // are one filter, not two requests.
    const wantedMembers = new Map(
      createdBy.positives
        .flatMap(resolve)
        .map((member) => [member.uuid, member]),
    );
    const wanted = new Set(wantedMembers.keys());
    const excluded = new Set(
      createdBy.negatives.flatMap(resolve).map((member) => member.uuid),
    );
    if (createdBy.negatives.length === 0 && wanted.size === 1) {
      server.createdBy = [...wantedMembers.values()][0].id;
    } else {
      if (createdBy.positives.length > 0) {
        if (createdBy.negatives.length === 0 && wanted.size > 1) {
          fanouts.push(
            [...wantedMembers.values()].map((member) => ({
              createdBy: member.id,
            })),
          );
        }
        predicates.push(
          wanted.size === 0
            ? MATCH_NONE
            : (task) => !!task.created_by && wanted.has(task.created_by.uuid),
        );
      }
      if (excluded.size > 0) {
        predicates.push(
          (task) => !task.created_by || !excluded.has(task.created_by.uuid),
        );
      }
    }
  }

  const space = groups.get("space");
  if (space) {
    const resolve = (token: FeedQueryToken): FeedQuerySpace | undefined => {
      const value = normalize(token.value).replace(/^#/, "");
      const matched = context.spaces.find((s) => normalize(s.name) === value);
      if (!matched) {
        issues.push({
          raw: token.raw,
          kind: "unknown-value",
          message: `No space named "${token.value}"`,
        });
      }
      return matched;
    };
    const wanted = new Set(
      space.positives.map(resolve).flatMap((s) => (s ? [s.id] : [])),
    );
    const excluded = new Set(
      space.negatives.map(resolve).flatMap((s) => (s ? [s.id] : [])),
    );
    if (space.negatives.length === 0 && wanted.size === 1) {
      server.channel = [...wanted][0];
    } else {
      if (space.positives.length > 0) {
        if (space.negatives.length === 0 && wanted.size > 1) {
          fanouts.push([...wanted].map((channel) => ({ channel })));
        }
        predicates.push(
          wanted.size === 0
            ? MATCH_NONE
            : (task) => !!task.channel && wanted.has(task.channel),
        );
      }
      if (excluded.size > 0) {
        predicates.push((task) => !task.channel || !excluded.has(task.channel));
      }
    }
  }

  const repo = groups.get("repo");
  if (repo) {
    const matchesRepo = (task: FeedQueryTask, value: string) =>
      !!task.repository &&
      normalize(task.repository).includes(normalize(value));
    const values = [...new Set(repo.positives.map((t) => normalize(t.value)))];
    if (repo.negatives.length === 0 && values.length === 1) {
      server.repository = values[0];
    } else {
      if (values.length > 0) {
        if (repo.negatives.length === 0 && values.length > 1) {
          fanouts.push(values.map((repository) => ({ repository })));
        }
        predicates.push((task) =>
          values.some((value) => matchesRepo(task, value)),
        );
      }
      for (const token of repo.negatives) {
        predicates.push((task) => !matchesRepo(task, token.value));
      }
    }
  }

  const status = groups.get("status");
  if (status) {
    const values = new Set(status.positives.map((t) => t.value));
    if (status.negatives.length === 0 && values.size === 1) {
      server.status = [...values][0] as TaskRunStatus;
    } else {
      if (values.size > 0) {
        if (status.negatives.length === 0 && values.size > 1) {
          fanouts.push(
            [...values].map((value) => ({ status: value as TaskRunStatus })),
          );
        }
        predicates.push(
          (task) => !!task.latest_run && values.has(task.latest_run.status),
        );
      }
      if (status.negatives.length > 0) {
        const negated = new Set(status.negatives.map((t) => t.value));
        predicates.push(
          (task) => !task.latest_run || !negated.has(task.latest_run.status),
        );
      }
    }
  }

  const origin = groups.get("origin");
  if (origin) {
    const values = new Set(origin.positives.map((t) => normalize(t.value)));
    if (origin.negatives.length === 0 && values.size === 1) {
      server.originProduct = [...values][0];
    } else {
      if (values.size > 0) {
        if (origin.negatives.length === 0 && values.size > 1) {
          fanouts.push([...values].map((value) => ({ originProduct: value })));
        }
        predicates.push(
          (task) =>
            !!task.origin_product && values.has(normalize(task.origin_product)),
        );
      }
      if (origin.negatives.length > 0) {
        const negated = new Set(
          origin.negatives.map((t) => normalize(t.value)),
        );
        predicates.push(
          (task) =>
            !task.origin_product ||
            !negated.has(normalize(task.origin_product)),
        );
      }
    }
  }

  const archived = groups.get("archived");
  if (archived && archived.positives.length > 0) {
    // `-is:archived` is the default (the list excludes archived tasks), so
    // only the positive form changes the request.
    server.archived = true;
  }

  const pr = groups.get("pr");
  if (pr) {
    const hasPr = (task: FeedQueryTask) =>
      typeof task.latest_run?.output?.pr_url === "string";
    const addPrPredicate = (token: FeedQueryToken, positive: boolean) => {
      const value = normalize(token.value);
      if (!SUPPORTED_PR_VALUES.has(value)) return; // flagged as unsupported
      // `pr:none` ≡ `-pr:any`; fold the four spellings into one boolean.
      const mustHave = positive === (value === "any");
      predicates.push((task) => hasPr(task) === mustHave);
    };
    for (const token of pr.positives) addPrPredicate(token, true);
    for (const token of pr.negatives) addPrPredicate(token, false);
  }

  const matches =
    predicates.length === 0
      ? MATCH_ALL
      : (task: FeedQueryTask) => predicates.every((p) => p(task));

  // The cartesian product of the base request with each OR group's values.
  // A group whose fan-out would blow the cap keeps its predicate and skips
  // the fan-out — correct, just back to filtering the base request's page.
  let requests: FeedQueryServerParams[] = [server];
  for (const fanout of fanouts) {
    if (requests.length * fanout.length > MAX_PLAN_REQUESTS) continue;
    requests = requests.flatMap((request) =>
      fanout.map((params) => ({ ...request, ...params })),
    );
  }

  return { requests, matches, issues };
}
