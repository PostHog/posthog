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
 * - double quotes carry spaces (`space:"desktop app"`),
 * - person keys (`created-by:`, `commented-by:`, `mentions:`, `involves:`)
 *   accept `@me` and teammate names/emails.
 *
 * Unknown keys deliberately fall through to free text rather than erroring —
 * a URL's `https:` or a stray `re:` in pasted text must not break the query.
 * The autocomplete is what steers people onto real keys.
 */

/** Canonical filter keys. Aliases (`author:`, `channel:`, …) map onto these. */
export type FeedQueryKey =
  | "created-by"
  | "commented-by"
  | "mentions"
  | "involves"
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
  "commented-by": "commented-by",
  commenter: "commented-by",
  mentions: "mentions",
  mentioned: "mentions",
  involves: "involves",
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

/** Valid `is:` values beyond the status sugar. */
const IS_FLAG_VALUES: ReadonlySet<string> = new Set(["archived", "pinned"]);

export const PR_VALUES = [
  "any",
  "none",
  "open",
  "draft",
  "merged",
  "closed",
] as const;
export type PrValue = (typeof PR_VALUES)[number];

/** PR states beyond presence, in the backend's snapshot vocabulary
 * (`TaskRun.output.pr_state`, kept fresh by the PR webhook). */
const PR_STATE_VALUES: ReadonlySet<string> = new Set([
  "open",
  "draft",
  "merged",
  "closed",
]);

export const CI_VALUES = [
  "red",
  "failing",
  "green",
  "passing",
  "pending",
  "none",
] as const;

/** What `type:` can scope. Only the command palette acts on non-task kinds;
 * a feed carries tasks, so its planner flags the rest as ignored. */
export const TYPE_VALUES = ["task", "space", "command", "feed"] as const;
export type TypeValue = (typeof TYPE_VALUES)[number];

/** Friendlier spellings onto the backend's snapshot vocabulary
 * (`TaskRun.output.ci_status`, kept fresh by the CI follow-up loop). */
const CI_ALIASES: Record<string, string> = {
  red: "failing",
  green: "passing",
};

/**
 * The words people reach for onto the backend's `origin_product` enum
 * (`Task.OriginProduct`): a desktop-created task is stored as user_created,
 * a scout's as signals_scout. Unknown origins pass through untouched — the
 * enum grows server-side and an unaliased value still filters exactly.
 */
export const ORIGIN_ALIASES: Record<string, string> = {
  desktop: "user_created",
  user: "user_created",
  scout: "signals_scout",
  signals: "signal_report",
  ai: "posthog_ai",
  max: "posthog_ai",
  errors: "error_tracking",
  support: "support_queue",
  replay: "session_summaries",
};

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
      if (!IS_FLAG_VALUES.has(value) && !IS_STATUS_SUGAR[value]) {
        issues.push({
          raw: token.raw,
          kind: "unknown-value",
          message: `Unknown "is:" value "${token.value}". Expected one of: archived, pinned, running, done, failed`,
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
      }
      return;
    }
    case "type": {
      if (!TYPE_VALUES.includes(value as (typeof TYPE_VALUES)[number])) {
        issues.push({
          raw: token.raw,
          kind: "unknown-value",
          message: `Unknown "type:" value "${token.value}". Expected one of: ${TYPE_VALUES.join(", ")}`,
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
    /** Valid, but nothing can act on it yet. No key produces this today;
     * kept so a future key can ship its syntax before its filter. */
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
  /** PR state of the latest run's pull request (open/draft/merged/closed). */
  prState?: string;
  /** CI rollup on the latest run's pull request (passing/failing/pending/none). */
  ciStatus?: string;
  /** Only tasks the requesting user has pinned. */
  pinned?: boolean;
  /** Tasks carrying a thread comment by this user id. */
  commentedBy?: number;
  /** Tasks whose thread mentions this user id. */
  mentions?: number;
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

/** The result kind a query's `type:` token scopes to, or null for all. */
export function feedQueryTypeScope(parsed: ParsedFeedQuery): TypeValue | null {
  const token = parsed.tokens.find(
    (t) =>
      t.key === "type" &&
      !t.negated &&
      TYPE_VALUES.includes(normalize(t.value) as TypeValue),
  );
  return token ? (normalize(token.value) as TypeValue) : null;
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
  const pinned = positives("is").some((t) => normalize(t.value) === "pinned");

  const personWord = (value: string) =>
    value === "@me" || value === "me" ? "me" : capitalize(value);
  const peoplePhrase = (key: FeedQueryKey, lead: string) => {
    const names = [
      ...new Set(positives(key).map((t) => personWord(normalize(t.value)))),
    ];
    return names.length > 0 ? `${lead} ${names.join(" or ")}` : "";
  };
  const repos = positives("repo").map((t) => t.value);
  const spaces = positives("space").map((t) => t.value.replace(/^#/, ""));
  const prValue = positives("pr")
    .map((t) => normalize(t.value))
    .find((v) => PR_VALUES.includes(v as PrValue));
  const ciValue = positives("ci")
    .map((t) => CI_ALIASES[normalize(t.value)] ?? normalize(t.value))
    .find((v) => v === "failing" || v === "passing" || v === "pending");

  const head = [
    possessive,
    pinned ? "pinned" : "",
    archived ? "archived" : "",
    statusWords.join(" or "),
    parsed.text,
  ]
    .filter(Boolean)
    .join(" ");
  const places = [...spaces, ...repos];
  const prPhrase =
    prValue === "any"
      ? "with a PR"
      : prValue === "none"
        ? "without a PR"
        : prValue
          ? `with ${/^[aeiou]/.test(prValue) ? "an" : "a"} ${prValue} PR`
          : "";
  const tail = [
    peoplePhrase("involves", "involving"),
    peoplePhrase("commented-by", "commented on by"),
    peoplePhrase("mentions", "mentioning"),
    places.length > 0 ? `in ${places.join(" or ")}` : "",
    prPhrase,
    ciValue ? `with ${ciValue} CI` : "",
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

/** One OR group's per-value request params, waiting to be multiplied into
 * the request list. */
interface PlanFanout {
  params: Partial<FeedQueryServerParams>[];
  /**
   * A client predicate re-checks this group, so skipping the fan-out at the
   * request cap only costs recall. Unverified groups (comments, mentions —
   * data the task payload doesn't carry) have no predicate: they expand
   * first, and get flagged rather than silently dropped when they can't.
   */
  verified: boolean;
  /** A chunk from the group, for the issue when the fan-out is skipped. */
  raw: string;
}

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
  const fanouts: PlanFanout[] = [];
  const predicates: ((task: FeedQueryTask) => boolean)[] = [];
  const issues: FeedQueryIssue[] = [...parsed.issues];

  if (parsed.text) server.search = parsed.text;

  // Name resolution for every person-valued key (created-by, commented-by,
  // mentions, involves), flagging spellings that name nobody.
  const resolveMembers = (token: FeedQueryToken): FeedQueryMember[] => {
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
  // Unique members across a group's positive tokens: two spellings of one
  // person are one filter, not two requests.
  const uniqueMembers = (tokens: FeedQueryToken[]): FeedQueryMember[] => [
    ...new Map(
      tokens.flatMap(resolveMembers).map((member) => [member.uuid, member]),
    ).values(),
  ];

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
      } else if (IS_FLAG_VALUES.has(normalize(token.value))) {
        key = normalize(token.value);
        value = key;
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
    const wantedMembers = uniqueMembers(createdBy.positives);
    const wanted = new Set(wantedMembers.map((member) => member.uuid));
    const excluded = new Set(
      createdBy.negatives.flatMap(resolveMembers).map((member) => member.uuid),
    );
    if (createdBy.negatives.length === 0 && wanted.size === 1) {
      server.createdBy = wantedMembers[0].id;
    } else {
      if (createdBy.positives.length > 0) {
        if (createdBy.negatives.length === 0 && wanted.size > 1) {
          fanouts.push({
            params: wantedMembers.map((member) => ({ createdBy: member.id })),
            verified: true,
            raw: createdBy.positives[0].raw,
          });
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

  // Comments and mentions live on the thread, not the task payload, so these
  // filters are server-only: no client predicate can re-check them, and a
  // negation has nothing to read — it reports itself ignored instead.
  const serverOnlyPeopleGroup = (
    groupKey: "commented-by" | "mentions",
    param: "commentedBy" | "mentions",
  ) => {
    const group = groups.get(groupKey);
    if (!group) return;
    for (const token of group.negatives) {
      issues.push({
        raw: token.raw,
        kind: "unsupported",
        message: `"-${groupKey}:" can't exclude yet, so it is ignored`,
      });
    }
    if (group.positives.length === 0) return;
    const members = uniqueMembers(group.positives);
    if (members.length === 0) {
      predicates.push(MATCH_NONE);
    } else if (members.length === 1) {
      server[param] = members[0].id;
    } else {
      fanouts.push({
        params: members.map((member) => ({ [param]: member.id })),
        verified: false,
        raw: group.positives[0].raw,
      });
    }
  };
  serverOnlyPeopleGroup("commented-by", "commentedBy");
  serverOnlyPeopleGroup("mentions", "mentions");

  const involves = groups.get("involves");
  if (involves) {
    for (const token of involves.negatives) {
      issues.push({
        raw: token.raw,
        kind: "unsupported",
        message: `"-involves:" can't exclude yet, so it is ignored`,
      });
    }
    if (involves.positives.length > 0) {
      // `involves:x` is creator-OR-commenter, spelled as one request per leg.
      // Alongside a created-by/commented-by filter the legs would overwrite
      // that filter's params in the cartesian product, so the combination
      // reports itself ignored rather than quietly widening the query.
      if (groups.has("created-by") || groups.has("commented-by")) {
        issues.push({
          raw: involves.positives[0].raw,
          kind: "unsupported",
          message: `"involves:" can't combine with "created-by:" or "commented-by:" yet, so it is ignored`,
        });
      } else {
        const members = uniqueMembers(involves.positives);
        if (members.length === 0) {
          predicates.push(MATCH_NONE);
        } else {
          fanouts.push({
            params: members.flatMap((member) => [
              { createdBy: member.id },
              { commentedBy: member.id },
            ]),
            verified: false,
            raw: involves.positives[0].raw,
          });
        }
      }
    }
  }

  const typeGroup = groups.get("type");
  if (typeGroup) {
    // `type:` scopes the command palette's result kinds. A feed's results are
    // tasks by definition: `type:task` is a no-op and the rest say so.
    for (const token of [...typeGroup.positives, ...typeGroup.negatives]) {
      if (normalize(token.value) !== "task") {
        issues.push({
          raw: token.raw,
          kind: "unsupported",
          message: `Feeds only carry tasks, so "${token.raw}" is ignored here`,
        });
      }
    }
  }

  const pinnedGroup = groups.get("pinned");
  if (pinnedGroup) {
    // Pins are per-user and not on the task payload, so like archived only
    // the positive form changes the request — but unlike archived, excluding
    // isn't the default, so the negation says it is ignored.
    if (pinnedGroup.positives.length > 0) server.pinned = true;
    for (const token of pinnedGroup.negatives) {
      issues.push({
        raw: token.raw,
        kind: "unsupported",
        message: `"-is:pinned" can't exclude yet, so it is ignored`,
      });
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
          fanouts.push({
            params: [...wanted].map((channel) => ({ channel })),
            verified: true,
            raw: space.positives[0].raw,
          });
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
          fanouts.push({
            params: values.map((repository) => ({ repository })),
            verified: true,
            raw: repo.positives[0].raw,
          });
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
          fanouts.push({
            params: [...values].map((value) => ({
              status: value as TaskRunStatus,
            })),
            verified: true,
            raw: status.positives[0].raw,
          });
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

  const originValue = (token: FeedQueryToken): string => {
    const value = normalize(token.value);
    return ORIGIN_ALIASES[value] ?? value;
  };
  const origin = groups.get("origin");
  if (origin) {
    const values = new Set(origin.positives.map(originValue));
    if (origin.negatives.length === 0 && values.size === 1) {
      server.originProduct = [...values][0];
    } else {
      if (values.size > 0) {
        if (origin.negatives.length === 0 && values.size > 1) {
          fanouts.push({
            params: [...values].map((value) => ({ originProduct: value })),
            verified: true,
            raw: origin.positives[0].raw,
          });
        }
        predicates.push(
          (task) =>
            !!task.origin_product && values.has(normalize(task.origin_product)),
        );
      }
      if (origin.negatives.length > 0) {
        const negated = new Set(origin.negatives.map(originValue));
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
    // The state the API last observed for the run's PR. Runs merged before
    // pr_state existed only carry the older pr_merged flag; honor both.
    const prStateOf = (task: FeedQueryTask): string | undefined => {
      const output = task.latest_run?.output;
      const state = output?.pr_state;
      if (typeof state === "string") return state;
      return output?.pr_merged === true ? "merged" : undefined;
    };
    const hasPr = (task: FeedQueryTask) =>
      typeof task.latest_run?.output?.pr_url === "string" ||
      prStateOf(task) !== undefined;
    const testFor = (value: string) =>
      value === "any"
        ? hasPr
        : value === "none"
          ? (task: FeedQueryTask) => !hasPr(task)
          : (task: FeedQueryTask) => prStateOf(task) === value;

    // Unknown values were flagged by the parser; filtering on them would
    // silently match nothing, so they take no part in the plan.
    const valid = (values: FeedQueryToken[]) => [
      ...new Set(
        values
          .map((t) => normalize(t.value))
          .filter((v) => PR_VALUES.includes(v as PrValue)),
      ),
    ];
    const positives = valid(pr.positives);
    const negatives = valid(pr.negatives);
    const states = positives.filter((v) => PR_STATE_VALUES.has(v));

    if (
      negatives.length === 0 &&
      positives.length === 1 &&
      states.length === 1
    ) {
      server.prState = states[0];
    } else {
      // Presence (any/none) has no server spelling, so a group carrying it
      // stays client-side; a pure state OR fans out like the other keys.
      if (
        negatives.length === 0 &&
        states.length > 1 &&
        states.length === positives.length
      ) {
        fanouts.push({
          params: states.map((prState) => ({ prState })),
          verified: true,
          raw: pr.positives[0].raw,
        });
      }
      if (positives.length > 0) {
        const tests = positives.map(testFor);
        predicates.push((task) => tests.some((test) => test(task)));
      }
      for (const value of negatives) {
        const test = testFor(value);
        predicates.push((task) => !test(task));
      }
    }
  }

  const ci = groups.get("ci");
  if (ci) {
    const ciStatusOf = (task: FeedQueryTask): string | undefined => {
      const status = task.latest_run?.output?.ci_status;
      return typeof status === "string" ? status : undefined;
    };
    const valid = (values: FeedQueryToken[]) => [
      ...new Set(
        values
          .map((t) => normalize(t.value))
          .filter((v) => CI_VALUES.includes(v as (typeof CI_VALUES)[number]))
          .map((v) => CI_ALIASES[v] ?? v),
      ),
    ];
    const positives = valid(ci.positives);
    const negatives = valid(ci.negatives);

    if (negatives.length === 0 && positives.length === 1) {
      server.ciStatus = positives[0];
    } else {
      if (negatives.length === 0 && positives.length > 1) {
        fanouts.push({
          params: positives.map((ciStatus) => ({ ciStatus })),
          verified: true,
          raw: ci.positives[0].raw,
        });
      }
      if (positives.length > 0) {
        const wanted = new Set(positives);
        predicates.push((task) => {
          const status = ciStatusOf(task);
          return status !== undefined && wanted.has(status);
        });
      }
      if (negatives.length > 0) {
        const excluded = new Set(negatives);
        predicates.push((task) => {
          const status = ciStatusOf(task);
          return status === undefined || !excluded.has(status);
        });
      }
    }
  }

  const matches =
    predicates.length === 0
      ? MATCH_ALL
      : (task: FeedQueryTask) => predicates.every((p) => p(task));

  // The cartesian product of the base request with each OR group's values.
  // Unverified groups expand first — nothing re-checks them client-side. A
  // verified group that would blow the cap skips its fan-out silently (its
  // predicate still filters the base page); an unverified one says so.
  const ordered = [...fanouts].sort(
    (a, b) => Number(a.verified) - Number(b.verified),
  );
  let requests: FeedQueryServerParams[] = [server];
  for (const fanout of ordered) {
    if (requests.length * fanout.params.length > MAX_PLAN_REQUESTS) {
      if (!fanout.verified) {
        issues.push({
          raw: fanout.raw,
          kind: "unsupported",
          message:
            "This query fans out into too many searches, so part of it is ignored",
        });
      }
      continue;
    }
    requests = requests.flatMap((request) =>
      fanout.params.map((params) => ({ ...request, ...params })),
    );
  }

  return { requests, matches, issues };
}
