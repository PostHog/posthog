import type { TaskRunStatus } from "@posthog/shared/domain-types";

// Unknown keys remain free text so pasted URLs and incomplete filters still search.
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
  | "type"
  | "saved";

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
  saved: "saved",
};

export const TASK_RUN_STATUSES: readonly TaskRunStatus[] = [
  "not_started",
  "queued",
  "in_progress",
  "completed",
  "failed",
  "cancelled",
];

const STATUS_ALIASES: Record<string, TaskRunStatus> = {
  running: "in_progress",
  done: "completed",
};

const IS_STATUS_SUGAR: Record<string, TaskRunStatus> = {
  running: "in_progress",
  done: "completed",
  failed: "failed",
};

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

export const TYPE_VALUES = [
  "task",
  "space",
  "command",
  "saved",
  "report",
] as const;
export type TypeValue = (typeof TYPE_VALUES)[number];

const CI_ALIASES: Record<string, string> = {
  red: "failing",
  green: "passing",
};

// Keep unknown origins unchanged so new server-side enum values remain searchable.
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
  raw: string;
  key: FeedQueryKey;
  value: string;
  negated: boolean;
}

export type FeedQueryIssueKind = "unknown-value" | "unsupported";

export interface FeedQueryIssue {
  raw: string;
  kind: FeedQueryIssueKind;
  message: string;
}

export interface ParsedFeedQuery {
  text: string;
  tokens: FeedQueryToken[];
  issues: FeedQueryIssue[];
}

// A quoted value remains part of its token when it contains spaces.
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

export interface FeedQuerySegment {
  start: number;
  raw: string;
  kind: "whitespace" | "text" | "token";
  token?: {
    key: FeedQueryKey;
    value: string;
    negated: boolean;
    invalid: boolean;
    unsupported: boolean;
  };
}

export function lexFeedQuery(query: string): FeedQuerySegment[] {
  const segments: FeedQuerySegment[] = [];
  let cursor = 0;
  for (const match of query.matchAll(CHUNK_RE)) {
    const start = match.index;
    if (start > cursor) {
      segments.push({
        start: cursor,
        raw: query.slice(cursor, start),
        kind: "whitespace",
      });
    }
    const raw = match[0];
    cursor = start + raw.length;

    const tokenMatch = TOKEN_RE.exec(raw);
    const key = tokenMatch
      ? KEY_ALIASES[tokenMatch[2].toLowerCase()]
      : undefined;
    if (!tokenMatch || !key || tokenMatch[3] === "") {
      segments.push({ start, raw, kind: "text" });
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
      start,
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
    segments.push({
      start: cursor,
      raw: query.slice(cursor),
      kind: "whitespace",
    });
  }
  return segments;
}

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

export interface FeedQueryPlanContext {
  members: readonly FeedQueryMember[];
  spaces: readonly FeedQuerySpace[];
  me?: FeedQueryMember | null;
  /**
   * Whether the `posthog-desktop-channel-reports` rollout is on. With it off,
   * `type:report` is treated as an unsupported token rather than flipping the
   * feed into reports-only mode, so the rollout flag stays a single switch.
   */
  reportsEnabled: boolean;
}

export interface FeedQueryServerParams {
  search?: string;
  createdBy?: number;
  channel?: string;
  repository?: string;
  status?: TaskRunStatus;
  originProduct?: string;
  archived?: boolean;
  prState?: string;
  ciStatus?: string;
  pinned?: boolean;
  commentedBy?: number;
  mentions?: number;
}

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

/** The report fields the reports-mode predicate reads. */
export interface FeedQueryReport {
  title?: string | null;
  status: string;
}

export interface FeedQueryPlan {
  /** What the feed fetches: tasks (the default) or reports (`type:report`). */
  mode: "tasks" | "reports";
  /** Requests to union for this query. Repeated values create one request per value. */
  requests: FeedQueryServerParams[];
  matches: (task: FeedQueryTask) => boolean;
  issues: FeedQueryIssue[];
  /** Reports-mode server narrowing: the one space to fetch, when `space:` names one. */
  reportChannelId?: string;
  /** Reports-mode client predicate (free-text title match, archived exclusion). */
  matchesReport?: (report: FeedQueryReport) => boolean;
}

function normalize(value: string): string {
  return value.trim().toLowerCase();
}

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

const STATUS_WORDS: Partial<Record<string, string>> = {
  in_progress: "running",
  completed: "done",
  not_started: "not started",
};

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

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

/** Limit fan-out requests so one query cannot overload the task-list API. */
const MAX_PLAN_REQUESTS = 8;

/** Per-value request parameters for one OR group. */
interface PlanFanout {
  params: Partial<FeedQueryServerParams>[];
  /** True when the task payload can recheck this group after fetching. */
  verified: boolean;
  /** Token to show when the fan-out limit skips this group. */
  raw: string;
}

/** Compiles a parsed query into task-list requests and a client-side predicate. */
export function planFeedQuery(
  parsed: ParsedFeedQuery,
  context: FeedQueryPlanContext,
): FeedQueryPlan {
  const server: FeedQueryServerParams = {};
  // Combine the base request with every OR group's request parameters.
  const fanouts: PlanFanout[] = [];
  const predicates: ((task: FeedQueryTask) => boolean)[] = [];
  const issues: FeedQueryIssue[] = [...parsed.issues];

  if (parsed.text) server.search = parsed.text;

  // Resolve people before building the task-list requests.
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
  // Equivalent names for one person must not create duplicate requests.
  const uniqueMembers = (tokens: FeedQueryToken[]): FeedQueryMember[] => [
    ...new Map(
      tokens.flatMap(resolveMembers).map((member) => [member.uuid, member]),
    ).values(),
  ];

  // Normalize aliases before grouping so equivalent filters do not become AND conditions.
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

  // `type:report` flips the whole feed into reports-only mode: reports are a
  // different resource with different filters, so the plan swaps its fetch
  // strategy instead of mixing kinds. Handled before the task groups so their
  // tokens surface as "unsupported here" rather than half-applying. Gated on the
  // reports rollout: with the flag off, the token falls through to the task-mode
  // `type:` handling below, which reports it as unsupported.
  if (
    context.reportsEnabled &&
    groups
      .get("type")
      ?.positives.some((token) => normalize(token.value) === "report")
  ) {
    return planReportFeedQuery(parsed, groups, context, issues);
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

  // Thread comments and mentions are absent from the task payload, so only the API can filter them.
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
      // This expands to creator and commenter requests, which conflict with either explicit filter.
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
    // Feed results contain tasks only, so `type:` carries no meaning here. A
    // negated `-type:task` is self-contradictory rather than the identity, so
    // it is reported as ignored too instead of silently dropping to MATCH_ALL.
    for (const token of [...typeGroup.positives, ...typeGroup.negatives]) {
      if (token.negated || normalize(token.value) !== "task") {
        issues.push({
          raw: token.raw,
          kind: "unsupported",
          message: `Feeds only carry tasks, so "${token.raw}" is ignored here`,
        });
      }
    }
  }

  const savedGroup = groups.get("saved");
  if (savedGroup) {
    // `saved:` selects a saved search in the command palette, not its task results.
    for (const token of [...savedGroup.positives, ...savedGroup.negatives]) {
      issues.push({
        raw: token.raw,
        kind: "unsupported",
        message: `"saved:" opens saved searches from the command palette, so it is ignored here`,
      });
    }
  }

  const pinnedGroup = groups.get("pinned");
  if (pinnedGroup) {
    // Pin data is per-user and absent from task payloads, so a negation cannot be rechecked.
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
  if (archived) {
    // Task lists exclude archived tasks unless the query includes them.
    if (archived.positives.length > 0 && archived.negatives.length > 0) {
      predicates.push(MATCH_NONE);
    } else if (archived.positives.length > 0) {
      server.archived = true;
    }
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

    // Ignore values the parser already marked invalid to avoid an empty result.
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
      // PR presence has no API filter, so it remains a client-side predicate.
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

  // Expand unverified groups first because the task payload cannot recheck them.
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
            "Use fewer filter values. This query requires too many searches.",
        });
      }
      continue;
    }
    requests = requests.flatMap((request) =>
      fanout.params.map((params) => ({ ...request, ...params })),
    );
  }

  return { mode: "tasks", requests, matches, issues };
}

// Suppressed, resolved, and deleted reports live in the archive, not in feeds.
const REPORT_EXCLUDED_STATUSES = new Set(["suppressed", "resolved", "deleted"]);

/**
 * The reports-only plan behind `type:report`. Deliberately narrow: `space:`
 * scopes the fetch to one space and free text matches report titles; every
 * other token is task-shaped and reported as unsupported rather than
 * half-applied.
 */
function planReportFeedQuery(
  parsed: ParsedFeedQuery,
  groups: Map<string, Group>,
  context: FeedQueryPlanContext,
  issues: FeedQueryIssue[],
): FeedQueryPlan {
  let reportChannelId: string | undefined;
  // A positive space: that doesn't resolve must narrow to nothing, not broaden
  // to every report — mirrors the task-mode MATCH_NONE for an unknown space.
  let unresolvedSpace = false;

  for (const [key, group] of groups) {
    if (key === "type") {
      for (const token of [...group.positives, ...group.negatives]) {
        if (token.negated || normalize(token.value) !== "report") {
          issues.push({
            raw: token.raw,
            kind: "unsupported",
            message: `A report feed shows only reports, so "${token.raw}" is ignored here`,
          });
        }
      }
      continue;
    }
    if (key === "space") {
      for (const token of [...group.positives.slice(1), ...group.negatives]) {
        issues.push({
          raw: token.raw,
          kind: "unsupported",
          message: `Report feeds support one "space:" filter, so "${token.raw}" is ignored here`,
        });
      }
      const first = group.positives[0];
      if (first) {
        const value = normalize(first.value).replace(/^#/, "");
        const matched = context.spaces.find((s) => normalize(s.name) === value);
        if (matched) {
          reportChannelId = matched.id;
        } else {
          unresolvedSpace = true;
          issues.push({
            raw: first.raw,
            kind: "unknown-value",
            message: `No space named "${first.value}"`,
          });
        }
      }
      continue;
    }
    for (const token of [...group.positives, ...group.negatives]) {
      issues.push({
        raw: token.raw,
        kind: "unsupported",
        message: `Report feeds don't support "${token.raw}" yet, so it is ignored`,
      });
    }
  }

  const text = normalize(parsed.text);
  const matchesReport = (report: FeedQueryReport): boolean => {
    if (unresolvedSpace) return false;
    if (REPORT_EXCLUDED_STATUSES.has(report.status)) return false;
    if (!text) return true;
    return (report.title ?? "").toLowerCase().includes(text);
  };

  return {
    mode: "reports",
    requests: [],
    matches: MATCH_NONE,
    issues,
    reportChannelId,
    matchesReport,
  };
}
