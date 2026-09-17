import { readdir, readFile, stat } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import {
  createSandboxPosthogClient,
  withReportDeadline,
} from "../../../signed-commit-artefacts";
import { defineLocalTool, type LocalToolResult } from "../registry";

const MAX_ACTIVITIES_PER_RUN = 12;
const ATTACHMENTS_DIR = ".posthog/attachments";
const MAX_LOG_BYTES = 128 * 1024 * 1024;
const IDLE_GAP_SECONDS = 240;
const MAX_COMMANDS = 24;
const MAX_GUIDANCE = 20;
const MAX_GUIDANCE_LENGTH = 200;

// Keep in step with SECRET_PATTERNS in products/tasks/backend/logic/services/task_analysis.py.
const SECRET_PATTERNS: RegExp[] = [
  /\bgh[opsur]_[A-Za-z0-9]{20,}/,
  /github_pat_[A-Za-z0-9_]{20,}/,
  /\bsk-[A-Za-z0-9_-]{16,}/,
  /\bAKIA[0-9A-Z]{12,}/,
  /\bxox[abprs]-[A-Za-z0-9-]{10,}/,
  /\bph[aersx]_[A-Za-z0-9]{16,}/,
  /bearer\s+[A-Za-z0-9._~+/=-]{16,}/i,
  /-----BEGIN [A-Z ]*PRIVATE KEY-----/,
];

const GOAL_KINDS = [
  "orient",
  "explore",
  "gather",
  "produce",
  "verify",
  "setup_env",
  "ship",
  "wait",
  "operate",
  "deliver",
] as const;

const OUTCOMES = ["worked", "failed", "abandoned", "unknown"] as const;

const BLOCKER_KINDS = [
  "missing_binary",
  "missing_package",
  "service_down",
  "missing_build_artifact",
  "missing_credential",
  "memory_limit",
  "network",
  "shallow_git",
  "tool_error",
  "tool_syntax",
  "api_error",
  "missing_flag",
  "unclear_instructions",
  "user_redirect",
] as const;

const GUIDANCE_PATTERN =
  /(?:\.agents|\.claude)\/skills\/[\w-]+|products\/[\w-]+\/skills\/[\w-]+|AGENTS\.md|CLAUDE\.md|pull_request_template\.md|\/context\/[\w./-]+\.md/g;
const SKILL_TITLE_PATTERN = /^Skill:\s*([\w-]+)/i;
const SKILL_TOOL_PATTERN = /(?:^|\/)skills?[-_]?get$/i;
const COMMAND_KINDS = new Set(["execute", "read", "search"]);
const SKIPPED_HEADS = new Set(["echo", "cd", "export", "true"]);
const TWO_WORD_HEADS = new Set([
  "git",
  "gh",
  "docker",
  "pnpm",
  "npm",
  "uv",
  "hogli",
  "python3",
  "python",
  "flox",
  "sudo",
  "apt-get",
  "apt",
]);

interface ComputedActivityMetrics {
  tool_calls: number;
  failed_calls: number;
  seconds: number;
  idle_seconds: number;
  commands: string[];
  guidance_read: string[];
}

interface ParsedLine {
  raw: string;
  decoded: string;
  timestamp: number | null;
  callStarted: boolean;
  callFailed: boolean;
  callId: string | null;
  command: string | null;
  guidance: string[];
}

interface RecordedRange {
  index: number;
  start: number;
  end: number;
}

let reportQueue: Promise<unknown> = Promise.resolve();
function enqueueReport<T>(run: () => Promise<T>): Promise<T> {
  const result = reportQueue.then(run, run);
  reportQueue = result.catch(() => undefined);
  return result;
}

function errorResult(message: string): LocalToolResult {
  return { content: [{ type: "text", text: message }], isError: true };
}

// The API throws a raw `Failed request: [400] {...}` blob for a rejection, and a timeout or a
// dropped connection throws anything else. Only the first means the server saw the activity
// and refused it; the second is safe to retry because the server ignores an exact duplicate.
function reportFailureResult(error: unknown): LocalToolResult {
  const message = error instanceof Error ? error.message : String(error);
  if (/Failed request: \[4\d\d\]/.test(message)) {
    return errorResult(
      `The activity was rejected by the server and was not recorded. Correct the flagged field and call report_activity again. Server response: ${message}`,
    );
  }
  return errorResult(
    `The activity report did not complete (${message}). Call report_activity again with the same arguments; the server ignores an exact duplicate, so a retry cannot store it twice.`,
  );
}

// biome-ignore lint/suspicious/noControlCharactersInRegex: matching the ESC byte is the point
const ANSI_PATTERN = /(?:\u001b|\\u001b)\[[0-9;]*m/g;

function normalizeForMatch(text: string): string {
  return text.replace(ANSI_PATTERN, "").replace(/\s+/g, " ").trim();
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function containsWholeTerm(text: string, term: string): boolean {
  return new RegExp(
    `(?<![A-Za-z0-9_])${escapeRegExp(term)}(?![A-Za-z0-9_])`,
    "i",
  ).test(text);
}

async function findAttachedLog(cwd: string): Promise<string | null> {
  try {
    const root = path.join(cwd, ATTACHMENTS_DIR);
    const entries = await readdir(root, { recursive: true });
    const candidates = entries
      .map(String)
      .filter((entry) => entry.endsWith(".jsonl"))
      .sort(
        (a, b) =>
          Number(b.endsWith("run-log.jsonl")) -
          Number(a.endsWith("run-log.jsonl")),
      );
    return candidates.length > 0 ? path.join(root, candidates[0]) : null;
  } catch {
    return null;
  }
}

function collectStrings(value: unknown, sink: string[]): void {
  if (typeof value === "string") {
    sink.push(value);
    return;
  }
  if (Array.isArray(value)) {
    for (const item of value) collectStrings(item, sink);
    return;
  }
  if (value && typeof value === "object") {
    for (const item of Object.values(value)) collectStrings(item, sink);
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

// Codex puts the shell command in `title` and sends no `rawInput` at all. Claude sends an
// empty `rawInput` on `tool_call` and the real one on `tool_call_update`, and its title is a
// description, so an empty `rawInput` must not fall back to the title.
function commandFrom(call: Record<string, unknown>): string | null {
  const command = asRecord(call.rawInput)?.command;
  if (typeof command === "string" && command.trim()) return command;
  const title = call.title;
  if (
    !("rawInput" in call) &&
    COMMAND_KINDS.has(String(call.kind)) &&
    typeof title === "string" &&
    title.trim()
  ) {
    return title;
  }
  return null;
}

function skillNameFrom(call: Record<string, unknown>): string | null {
  const title = typeof call.title === "string" ? call.title : "";
  const fromTitle = title.match(SKILL_TITLE_PATTERN)?.[1];
  if (fromTitle) return fromTitle;
  const input = asRecord(call.rawInput);
  const named = input?.skill_name ?? input?.skill;
  if (typeof named === "string" && named.trim()) return named.trim();
  if (SKILL_TOOL_PATTERN.test(title) && typeof input?.name === "string") {
    return input.name;
  }
  return null;
}

function guidanceFrom(call: Record<string, unknown>): string[] {
  if (call.kind === "edit") return [];
  const found = new Set<string>();
  const skill = skillNameFrom(call);
  if (skill) found.add(`skill:${skill}`);
  const sources: string[] = [];
  collectStrings(call.rawInput, sources);
  collectStrings(call.locations, sources);
  if (typeof call.title === "string") sources.push(call.title);
  for (const source of sources) {
    for (const match of source.match(GUIDANCE_PATTERN) ?? []) {
      found.add(match.replace(/^.*\/context\//, "wiki/"));
    }
  }
  return [...found].map((entry) => entry.slice(0, MAX_GUIDANCE_LENGTH));
}

function parseLine(raw: string): ParsedLine {
  const line: ParsedLine = {
    raw,
    decoded: raw,
    timestamp: null,
    callStarted: false,
    callFailed: false,
    callId: null,
    command: null,
    guidance: [],
  };
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return line;
  }
  const decodedParts: string[] = [];
  collectStrings(parsed, decodedParts);
  line.decoded = decodedParts.join(" ");
  const record = asRecord(parsed);
  if (!record) return line;
  if (typeof record.timestamp === "string") {
    const ms = Date.parse(record.timestamp);
    if (!Number.isNaN(ms)) line.timestamp = ms;
  }
  const event = asRecord(record.event);
  const toolCall = asRecord(event?.toolCall);
  if (record.type === "pi_event" && event && toolCall) {
    line.callId = typeof toolCall.id === "string" ? toolCall.id : null;
    if (event.type === "tool_call_started") {
      line.callStarted = true;
      line.command = commandFrom(toolCall);
      line.guidance = guidanceFrom(toolCall);
    } else if (
      event.type === "tool_call_updated" &&
      toolCall.status === "failed"
    ) {
      line.callFailed = true;
    }
    return line;
  }
  const update = asRecord(
    asRecord(asRecord(record.notification)?.params)?.update,
  );
  if (!update) return line;
  line.callId =
    typeof update.toolCallId === "string" ? update.toolCallId : null;
  if (update.sessionUpdate === "tool_call") {
    line.callStarted = true;
    line.command = commandFrom(update);
    line.guidance = guidanceFrom(update);
  } else if (update.sessionUpdate === "tool_call_update") {
    line.command = commandFrom(update);
    line.guidance = guidanceFrom(update);
    if (update.status === "failed") line.callFailed = true;
  }
  return line;
}

interface ParsedLog {
  key: string;
  lines: ParsedLine[];
}

let logCache: ParsedLog | null = null;
const recordedRanges = new Map<string, RecordedRange[]>();

async function readParsedLog(cwd: string): Promise<ParsedLog | null> {
  const logPath = await findAttachedLog(cwd);
  if (!logPath) return null;
  try {
    const { size, mtimeMs } = await stat(logPath);
    if (size > MAX_LOG_BYTES) return null;
    const key = `${logPath}:${size}:${mtimeMs}`;
    if (logCache?.key === key) return logCache;
    const lines = (await readFile(logPath, "utf8")).split("\n");
    while (lines.length > 0 && lines[lines.length - 1].trim() === "") {
      lines.pop();
    }
    logCache = { key, lines: lines.map(parseLine) };
    return logCache;
  } catch {
    return null;
  }
}

function quoteCandidates(quote: string): string[] {
  const candidates = new Set([normalizeForMatch(quote)]);
  candidates.add(normalizeForMatch(JSON.stringify(quote).slice(1, -1)));
  try {
    const unescaped = JSON.parse(`"${quote.replace(/(?<!\\)"/g, '\\"')}"`);
    if (typeof unescaped === "string") {
      candidates.add(normalizeForMatch(unescaped));
    }
  } catch {}
  return [...candidates].filter((candidate) => candidate.length > 0);
}

function quoteAppearsInLines(quote: string, lines: ParsedLine[]): boolean {
  const candidates = quoteCandidates(quote);
  const raw = normalizeForMatch(lines.map((line) => line.raw).join("\n"));
  const decoded = normalizeForMatch(
    lines.map((line) => line.decoded).join(" "),
  );
  return candidates.some(
    (candidate) => raw.includes(candidate) || decoded.includes(candidate),
  );
}

// Splits on `&&`, `||`, `;`, `|`, and newlines outside single or double quotes, so a quoted
// pipe or semicolon inside a `python -c` or `jq` program does not become a command head.
function splitShellCommands(command: string): string[] {
  const parts: string[] = [];
  let current = "";
  let quote: string | null = null;
  for (let i = 0; i < command.length; i++) {
    const char = command[i];
    if (quote) {
      current += char;
      if (char === "\\" && quote === '"' && i + 1 < command.length) {
        current += command[++i];
      } else if (char === quote) {
        quote = null;
      }
      continue;
    }
    if (char === "'" || char === '"') {
      quote = char;
      current += char;
      continue;
    }
    if (char === "\\" && i + 1 < command.length) {
      current += char + command[++i];
      continue;
    }
    if (char === "\n" || char === ";" || char === "|" || char === "&") {
      const pair = command.slice(i, i + 2);
      if (char === "&" && pair !== "&&") {
        current += char;
        continue;
      }
      parts.push(current);
      current = "";
      if (pair === "&&" || pair === "||") i += 1;
      continue;
    }
    current += char;
  }
  parts.push(current);
  return parts;
}

function commandHeads(command: string): string[] {
  const heads: string[] = [];
  for (const part of splitShellCommands(command)) {
    const words = part.trim().split(/\s+/).filter(Boolean);
    if (words.length === 0 || SKIPPED_HEADS.has(words[0])) continue;
    const head =
      TWO_WORD_HEADS.has(words[0]) && words.length > 1
        ? `${words[0]} ${words[1]}`
        : words[0];
    heads.push(head.slice(0, 60));
  }
  return heads;
}

function lastTimestampBefore(
  lines: ParsedLine[],
  index: number,
): number | null {
  for (let i = index - 1; i >= 0; i--) {
    if (lines[i].timestamp !== null) return lines[i].timestamp;
  }
  return null;
}

// `seconds` runs from the last timestamp before the range to the last timestamp inside it, so
// consecutive activities partition the run and a gap before an activity belongs to it.
function computeActivityMetrics(
  lines: ParsedLine[],
  startIndex: number,
  endIndex: number,
): ComputedActivityMetrics {
  const startedIds = new Set<string>();
  const failedIds = new Set<string>();
  let startedWithoutId = 0;
  let failedWithoutId = 0;
  const seenCommandIds = new Set<string>();
  const commands: string[] = [];
  const guidance = new Set<string>();
  const stamps: number[] = [];
  const before = lastTimestampBefore(lines, startIndex);
  if (before !== null) stamps.push(before);
  for (const line of lines.slice(startIndex, endIndex)) {
    if (line.timestamp !== null) stamps.push(line.timestamp);
    if (line.callStarted) {
      if (line.callId) startedIds.add(line.callId);
      else startedWithoutId += 1;
    }
    if (line.callFailed) {
      if (line.callId) failedIds.add(line.callId);
      else failedWithoutId += 1;
    }
    if (line.command) {
      const key = line.callId ?? `${commands.length}:${line.command}`;
      if (!seenCommandIds.has(key)) {
        seenCommandIds.add(key);
        for (const head of commandHeads(line.command)) {
          if (commands[commands.length - 1] !== head) commands.push(head);
        }
      }
    }
    for (const entry of line.guidance) guidance.add(entry);
  }
  const toolCalls = startedIds.size + startedWithoutId;
  const failedStarted = [...failedIds].filter((id) => startedIds.has(id));
  let seconds = 0;
  let idle = 0;
  if (stamps.length > 1) {
    seconds = Math.round((stamps[stamps.length - 1] - stamps[0]) / 1000);
    for (let i = 1; i < stamps.length; i++) {
      const gap = (stamps[i] - stamps[i - 1]) / 1000;
      if (gap > IDLE_GAP_SECONDS) idle += Math.round(gap);
    }
  }
  return {
    tool_calls: toolCalls,
    failed_calls: Math.min(toolCalls, failedStarted.length + failedWithoutId),
    seconds: Math.max(0, seconds),
    idle_seconds: Math.min(Math.max(0, idle), Math.max(0, seconds)),
    commands: commands.slice(0, MAX_COMMANDS),
    guidance_read: [...guidance].sort().slice(0, MAX_GUIDANCE),
  };
}

function findSecretLike(record: unknown): string | null {
  const values: string[] = [];
  collectStrings(record, values);
  for (const value of values) {
    for (const pattern of SECRET_PATTERNS) {
      if (pattern.test(value)) return pattern.source;
    }
  }
  return null;
}

function overlappingRange(
  ranges: RecordedRange[],
  start: number,
  end: number,
): RecordedRange | null {
  return (
    ranges.find((range) => start <= range.end && end >= range.start) ?? null
  );
}

export const reportActivityTool = defineLocalTool({
  name: "report_activity",
  description:
    "Record one activity from a task-run analysis: a span of the run log where the agent worked toward one goal. " +
    `Call once per activity in log order, without overlapping line ranges (at most ${MAX_ACTIVITIES_PER_RUN} per run). ` +
    "Give the line range; the tool counts tool calls, failures, seconds, and idle time from those lines. " +
    "The evidence quote must appear inside the line range — copy it exactly from your jq output; the tool checks and rejects mismatches. " +
    "Do not suggest fixes. Record what the agent tried, how it ended, and what blocked it.",
  schema: {
    goal_kind: z
      .enum(GOAL_KINDS)
      .describe("Which kind of work the agent did in this span."),
    goal: z
      .string()
      .min(3)
      .max(80)
      .describe("What the agent tried, in 3 to 8 words."),
    outcome: z.enum(OUTCOMES).describe("How the activity ended for the agent."),
    blocker_kind: z
      .enum(BLOCKER_KINDS)
      .optional()
      .describe(
        "What stopped the agent, when something did. Omit for healthy work, including a test that failed on the agent's own code.",
      ),
    blocker_name: z
      .string()
      .min(1)
      .max(120)
      .optional()
      .describe(
        "The exact binary, package, service, file, flag, or error the blocker names. For missing_flag use '<command head> <flag>'. Required with blocker_kind.",
      ),
    repair: z
      .string()
      .min(1)
      .max(300)
      .optional()
      .describe(
        "The command or step that removed the blocker, when the agent found one. Requires blocker_kind.",
      ),
    evidence: z
      .string()
      .min(10)
      .max(200)
      .describe(
        "One exact quote from the run log inside the line range. Must contain blocker_name as a whole word when set.",
      ),
    start_line: z
      .number()
      .int()
      .min(1)
      .describe("First log line of the activity, 1-based."),
    end_line: z
      .number()
      .int()
      .min(1)
      .describe("Last log line of the activity, 1-based."),
  },
  alwaysLoad: true,
  isEnabled: (ctx, meta) =>
    meta?.environment === "cloud" &&
    meta?.taskOriginProduct === "task_analysis" &&
    !!ctx.taskId &&
    !!ctx.taskRunId,
  handler: (ctx, args): Promise<LocalToolResult> =>
    enqueueReport(async () => {
      if (!ctx.taskId || !ctx.taskRunId) {
        return errorResult(
          "Activity reporting is not available in this session.",
        );
      }
      const client = createSandboxPosthogClient();
      if (!client) {
        return errorResult(
          "PostHog is not configured in this sandbox; the report cannot be saved.",
        );
      }
      if (args.end_line < args.start_line) {
        return errorResult("end_line must not be before start_line.");
      }
      if (args.blocker_kind && !args.blocker_name) {
        return errorResult(
          "blocker_kind requires blocker_name — name the exact binary, package, service, flag, or error.",
        );
      }
      if (args.blocker_name && !args.blocker_kind) {
        return errorResult("blocker_name requires blocker_kind.");
      }
      if (args.repair && !args.blocker_kind) {
        return errorResult(
          "repair requires blocker_kind — a repair only makes sense for a named blocker.",
        );
      }
      if (
        args.blocker_name &&
        !containsWholeTerm(args.evidence, args.blocker_name)
      ) {
        return errorResult(
          "evidence must contain blocker_name as a whole word — quote the log line that names the blocker.",
        );
      }
      if (findSecretLike(args)) {
        return errorResult(
          "The activity contains a credential-like token. Never include secrets — redact the token and keep only the non-secret part.",
        );
      }

      const log = await readParsedLog(ctx.cwd);
      if (log === null) {
        return errorResult(
          `No run log was found under ${ATTACHMENTS_DIR} (or it is too large to verify against). Evidence is verified against the attached .jsonl log; check the attachment exists.`,
        );
      }
      const { lines } = log;
      if (args.end_line > lines.length) {
        return errorResult(
          `end_line ${args.end_line} is past the end of the log (${lines.length} lines). The last line is ${lines.length}; check the range with wc -l.`,
        );
      }
      const ranges = recordedRanges.get(log.key) ?? [];
      const clash = overlappingRange(ranges, args.start_line, args.end_line);
      if (clash) {
        const nextStart = Math.max(...ranges.map((range) => range.end)) + 1;
        return errorResult(
          `Activity ${clash.index + 1} already covers lines ${clash.start}-${clash.end}. Activities arrive in log order without overlap; start this one at line ${nextStart} or later.`,
        );
      }
      const span = lines.slice(args.start_line - 1, args.end_line);
      if (!quoteAppearsInLines(args.evidence, span)) {
        return errorResult(
          `evidence was not found in log lines ${args.start_line}-${args.end_line} — copy the text exactly as your jq query printed it, and check the line range.`,
        );
      }

      const activity = {
        goal_kind: args.goal_kind,
        goal: args.goal,
        outcome: args.outcome,
        ...(args.blocker_kind && { blocker_kind: args.blocker_kind }),
        ...(args.blocker_name && { blocker_name: args.blocker_name }),
        ...(args.repair && { repair: args.repair }),
        evidence: args.evidence,
        start_line: args.start_line,
        end_line: args.end_line,
        ...computeActivityMetrics(lines, args.start_line - 1, args.end_line),
      };
      try {
        const { activity_index } = await withReportDeadline(
          (signal) =>
            client.reportAnalysisActivity(
              ctx.taskId as string,
              ctx.taskRunId as string,
              activity,
              signal,
            ),
          "activity report",
        );
        recordedRanges.set(log.key, [
          ...ranges,
          { index: activity_index, start: args.start_line, end: args.end_line },
        ]);
        const remaining = MAX_ACTIVITIES_PER_RUN - activity_index - 1;
        return {
          content: [
            {
              type: "text",
              text: `Recorded activity ${activity_index + 1} (${args.goal_kind}, ${args.outcome}) for lines ${args.start_line}-${args.end_line} of ${lines.length}: ${activity.tool_calls} tool calls, ${activity.failed_calls} failed, ${activity.seconds}s, ${activity.idle_seconds}s idle. ${remaining} more allowed; merge adjacent activities with the same goal_kind if the run needs more.`,
            },
          ],
        };
      } catch (error) {
        return reportFailureResult(error);
      }
    }),
});
