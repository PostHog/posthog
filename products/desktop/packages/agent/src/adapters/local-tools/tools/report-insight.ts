import { readdir, readFile, stat } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import {
  createSandboxPosthogClient,
  withReportDeadline,
} from "../../../signed-commit-artefacts";
import { defineLocalTool, type LocalToolResult } from "../registry";

export const INSIGHTS_STATE_KEY = "task_analysis_insights";
const MAX_INSIGHTS_PER_RUN = 5;
const ATTACHMENTS_DIR = ".posthog/attachments";
const MAX_LOG_BYTES = 128 * 1024 * 1024;

const SECRET_PATTERNS: RegExp[] = [
  /ghp_[A-Za-z0-9]{20,}/,
  /github_pat_[A-Za-z0-9_]{20,}/,
  /\bsk-[A-Za-z0-9_-]{16,}/,
  /\bAKIA[0-9A-Z]{12,}/,
  /\bxox[abprs]-[A-Za-z0-9-]{10,}/,
  /\bphx_[A-Za-z0-9]{20,}/,
  /bearer\s+[A-Za-z0-9._~+/=-]{16,}/i,
  /-----BEGIN [A-Z ]*PRIVATE KEY-----/,
];

const CATEGORIES = [
  "environment_failure",
  "missing_tool",
  "verbose_output",
  "redundant_work",
  "missing_capability",
  "instruction_gap",
  "wasted_retry",
  "other",
] as const;

const WASTED_EFFORT_REQUIRED_CATEGORIES = new Set([
  "environment_failure",
  "missing_tool",
  "verbose_output",
  "redundant_work",
  "wasted_retry",
]);

const evidenceSchema = z.object({
  quote: z
    .string()
    .min(20)
    .max(300)
    .describe(
      "Verbatim span copied from your jq query output. Checked against the raw run log; a paraphrase is rejected.",
    ),
  evidence_type: z.enum([
    "transcript_quote",
    "command_output",
    "measured_count",
  ]),
});

const suggestedFixSchema = z.object({
  change: z.string().min(50).max(400).describe("The specific change to make."),
  done_when: z
    .string()
    .min(30)
    .max(200)
    .describe(
      "A condition someone could actually check to confirm the fix worked.",
    ),
  setup_commands: z
    .array(z.string().min(1).max(500))
    .max(10)
    .optional()
    .describe("Single-line commands only; these may become image build steps."),
  required_services: z.array(z.string().min(1).max(100)).max(10).optional(),
  env_var_names: z
    .array(z.string().min(1).max(100))
    .max(10)
    .optional()
    .describe("Environment variable NAMES only. Never include a value."),
});

interface StoredInsight {
  [key: string]: unknown;
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

// Desktop ships on its own schedule with no orchestration against backend deploys, so a
// report can hit an older server contract (a 10-19 char quote, an output_bytes-only
// finding). The API throws a raw `Failed request: [400] {...}` blob that loses the finding
// silently. Turn a rejection into an actionable error so the model can correct the input
// and retry, matching the coaching style of every other rejection path in this tool.
function reportRejectionResult(error: unknown, what: string): LocalToolResult {
  const message = error instanceof Error ? error.message : String(error);
  return errorResult(
    `The ${what} was rejected by the server and was not recorded. Correct the flagged field and call report_insight again. Server response: ${message}`,
  );
}

// biome-ignore lint/suspicious/noControlCharactersInRegex: matching the ESC byte is the point
const ANSI_PATTERN = /(?:\u001b|\\u001b)\[[0-9;]*m/g;

function normalizeForMatch(text: string): string {
  return text.replace(ANSI_PATTERN, "").replace(/\s+/g, " ").trim();
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

interface LogHaystacks {
  raw: string;
  decoded: string;
}

let haystackCache: { key: string; haystacks: LogHaystacks } | null = null;

async function readLogHaystacks(cwd: string): Promise<LogHaystacks | null> {
  const logPath = await findAttachedLog(cwd);
  if (!logPath) return null;
  try {
    const { size, mtimeMs } = await stat(logPath);
    if (size > MAX_LOG_BYTES) return null;
    const cacheKey = `${logPath}:${size}:${mtimeMs}`;
    if (haystackCache?.key === cacheKey) return haystackCache.haystacks;
    const raw = await readFile(logPath, "utf8");
    const decodedParts: string[] = [];
    for (const line of raw.split("\n")) {
      try {
        collectStrings(JSON.parse(line), decodedParts);
      } catch {
        decodedParts.push(line);
      }
    }
    const haystacks: LogHaystacks = {
      raw: normalizeForMatch(raw),
      decoded: normalizeForMatch(decodedParts.join(" ")),
    };
    haystackCache = { key: cacheKey, haystacks };
    return haystacks;
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

function quoteAppearsInLog(quote: string, haystacks: LogHaystacks): boolean {
  return quoteCandidates(quote).some(
    (candidate) =>
      haystacks.raw.includes(candidate) ||
      haystacks.decoded.includes(candidate),
  );
}

function findSecretLike(finding: unknown): string | null {
  const values: string[] = [];
  collectStrings(finding, values);
  for (const value of values) {
    for (const pattern of SECRET_PATTERNS) {
      if (pattern.test(value)) return pattern.source;
    }
  }
  return null;
}

export const reportInsightTool = defineLocalTool({
  name: "report_insight",
  description:
    "File one verified inefficiency finding from a task-run analysis. Call once per finding (at most " +
    `${MAX_INSIGHTS_PER_RUN} per run), largest wasted effort first. Every evidence quote must appear ` +
    "in the attached run log — copy quotes exactly from your jq query output; the tool checks and rejects mismatches. " +
    "If the run has no findings, call once with only no_findings_reason. Zero findings is a valid result.",
  schema: {
    no_findings_reason: z
      .enum([
        "run_was_efficient",
        "too_short_to_judge",
        "insufficient_visibility",
      ])
      .optional()
      .describe(
        "Only for a run with zero findings; do not combine with a finding.",
      ),
    observation: z
      .string()
      .min(80)
      .max(500)
      .optional()
      .describe("What happened, 1-3 sentences."),
    evidence: z.array(evidenceSchema).min(1).max(3).optional(),
    occurrence_count: z.number().int().min(1).optional(),
    category: z.enum(CATEGORIES).optional(),
    other_justification: z.string().min(50).max(200).optional(),
    wasted_effort: z
      .object({
        tool_calls: z
          .number()
          .int()
          .min(1)
          .optional()
          .describe("Wasted tool calls, counted from the log."),
        seconds: z
          .number()
          .int()
          .min(1)
          .optional()
          .describe(
            "Wall-clock seconds across the wasted span, from the event timestamps bracketing it.",
          ),
        tokens: z
          .number()
          .int()
          .min(1)
          .optional()
          .describe(
            "Tokens consumed across the wasted span, measured from the run log.",
          ),
        output_bytes: z
          .number()
          .int()
          .min(1)
          .optional()
          .describe(
            "Sum of tool-output sizes across the wasted span, measured from the log. Works in both log formats even when token counters are absent.",
          ),
      })
      .optional()
      .describe(
        "Measured from the log, never guessed. Include every dimension the log supports; at least one is required for effort-based categories.",
      ),
    recurrence: z
      .enum(["every_run_in_this_repo", "runs_touching_this_area", "one_off"])
      .optional(),
    confidence_basis: z.enum(["directly_observed", "inferred"]).optional(),
    suggested_fix: suggestedFixSchema.optional(),
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
          "Insight reporting is not available in this session.",
        );
      }
      const client = createSandboxPosthogClient();
      if (!client) {
        return errorResult(
          "PostHog is not configured in this sandbox; the report cannot be saved.",
        );
      }

      if (args.no_findings_reason) {
        const findingFields = [
          args.observation,
          args.evidence,
          args.category,
          args.suggested_fix,
        ].filter((value) => value !== undefined);
        if (findingFields.length > 0) {
          return errorResult(
            "no_findings_reason cannot be combined with a finding. Either report the finding (drop no_findings_reason) or report no findings (drop every other field).",
          );
        }
        try {
          await withReportDeadline(
            (signal) =>
              client.reportAnalysisInsight(
                ctx.taskId as string,
                ctx.taskRunId as string,
                { no_findings_reason: args.no_findings_reason },
                signal,
              ),
            "no-findings report",
          );
        } catch (error) {
          return reportRejectionResult(error, "no-findings report");
        }
        return {
          content: [
            {
              type: "text",
              text: "Recorded: no findings for this run. Do not call report_insight again; summarize and finish.",
            },
          ],
        };
      }

      if (!args.observation || !args.evidence || !args.category) {
        return errorResult(
          "A finding requires observation, evidence, and category (or use only no_findings_reason for a clean run).",
        );
      }
      if (args.category === "other" && !args.other_justification) {
        return errorResult(
          "category 'other' requires other_justification (50-200 chars).",
        );
      }
      const wastedDimensions = Object.values(args.wasted_effort ?? {}).filter(
        (value) => value !== undefined,
      );
      if (
        WASTED_EFFORT_REQUIRED_CATEGORIES.has(args.category) &&
        wastedDimensions.length === 0
      ) {
        return errorResult(
          `category '${args.category}' requires wasted_effort with at least one measured dimension (tool_calls, seconds, tokens, or output_bytes) — count or subtract it from the log.`,
        );
      }
      if (!args.recurrence || !args.confidence_basis || !args.suggested_fix) {
        return errorResult(
          "A finding requires recurrence, confidence_basis, and suggested_fix.",
        );
      }
      for (const command of args.suggested_fix.setup_commands ?? []) {
        if (command.includes("\n")) {
          return errorResult(
            "setup_commands entries must be single-line. Chain steps with '&&'.",
          );
        }
      }
      for (const name of args.suggested_fix.env_var_names ?? []) {
        if (name.includes("=")) {
          return errorResult(
            "env_var_names carries names only — an entry contains '='. Remove the value; never report secrets.",
          );
        }
      }

      const secretField = findSecretLike(args);
      if (secretField) {
        return errorResult(
          "The finding contains a credential-like token. Never include secrets — redact the token and keep only the non-secret part of the evidence.",
        );
      }

      const haystacks = await readLogHaystacks(ctx.cwd);
      if (haystacks === null) {
        return errorResult(
          `No run log was found under ${ATTACHMENTS_DIR} (or it is too large to verify against). Evidence is verified against the attached .jsonl log; check the attachment exists.`,
        );
      }
      for (const [index, item] of args.evidence.entries()) {
        if (!quoteAppearsInLog(item.quote, haystacks)) {
          return errorResult(
            `evidence[${index}].quote was not found in the run log — copy the text exactly as your jq query printed it, not from memory.`,
          );
        }
      }

      const insight: StoredInsight = {
        observation: args.observation,
        evidence: args.evidence,
        occurrence_count: args.occurrence_count ?? 1,
        category: args.category,
        ...(args.other_justification && {
          other_justification: args.other_justification,
        }),
        ...(wastedDimensions.length > 0 && {
          wasted_effort: args.wasted_effort,
        }),
        recurrence: args.recurrence,
        confidence_basis: args.confidence_basis,
        suggested_fix: args.suggested_fix,
      };
      try {
        const { insight_index } = await withReportDeadline(
          (signal) =>
            client.reportAnalysisInsight(
              ctx.taskId as string,
              ctx.taskRunId as string,
              insight,
              signal,
            ),
          "insight report",
        );

        const remaining = MAX_INSIGHTS_PER_RUN - insight_index - 1;
        return {
          content: [
            {
              type: "text",
              text: `Recorded finding ${insight_index + 1} (${args.category}). ${remaining} more allowed; only report findings that clear the evidence bar.`,
            },
          ],
        };
      } catch (error) {
        return reportRejectionResult(error, "finding");
      }
    }),
});
