import { readFile } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import { createSandboxPosthogClient } from "../../../signed-commit-artefacts";
import { defineLocalTool, type LocalToolResult } from "../registry";

/**
 * Reporting channel for task-analysis runs (origin `task_analysis`): the agent
 * files one verified finding per call. The handler is the validator the skill
 * promises — every evidence quote is checked verbatim against the extracted
 * transcript on disk, and rejections carry a specific fix so the retry
 * converges. Findings accumulate in the run's own state, where the app renders
 * them and analytics collects them.
 */

export const INSIGHTS_STATE_KEY = "task_analysis_insights";
const MAX_INSIGHTS_PER_RUN = 5;
const TRANSCRIPT_FILENAME = "transcript.md";
const MAX_TRANSCRIPT_BYTES = 10 * 1024 * 1024;

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
      "Verbatim span copied from transcript.md. Checked against the file; a paraphrase is rejected.",
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

function errorResult(message: string): LocalToolResult {
  return { content: [{ type: "text", text: message }], isError: true };
}

function normalizeForMatch(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

async function readTranscript(cwd: string): Promise<string | null> {
  try {
    const transcriptPath = path.join(cwd, TRANSCRIPT_FILENAME);
    const content = await readFile(transcriptPath, "utf8");
    if (content.length > MAX_TRANSCRIPT_BYTES) return null;
    return content;
  } catch {
    return null;
  }
}

export const reportInsightTool = defineLocalTool({
  name: "report_insight",
  description:
    "File one verified inefficiency finding from a task-run analysis. Call once per finding (at most " +
    `${MAX_INSIGHTS_PER_RUN} per run), largest wasted effort first. Every evidence quote must appear ` +
    `verbatim in ${TRANSCRIPT_FILENAME} in the working directory — the tool checks and rejects mismatches. ` +
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
        metric: z.enum(["tool_calls", "minutes_estimated"]),
        amount: z.number().int().min(1),
      })
      .optional(),
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
  handler: async (ctx, args): Promise<LocalToolResult> => {
    if (!ctx.taskId || !ctx.taskRunId) {
      return errorResult("Insight reporting is not available in this session.");
    }
    const client = createSandboxPosthogClient();
    if (!client) {
      return errorResult(
        "PostHog is not configured in this sandbox; the report cannot be saved.",
      );
    }

    const run = await client.getTaskRun(ctx.taskId, ctx.taskRunId);
    const state = (run.state ?? {}) as Record<string, unknown>;
    const existing = Array.isArray(state[INSIGHTS_STATE_KEY])
      ? (state[INSIGHTS_STATE_KEY] as StoredInsight[])
      : [];

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
      if (existing.length > 0) {
        return errorResult(
          "Findings were already reported for this run, so a no-findings report is contradictory. Stop reporting.",
        );
      }
      await client.updateTaskRun(ctx.taskId, ctx.taskRunId, {
        state: {
          [INSIGHTS_STATE_KEY]: [
            { schema_version: 1, no_findings_reason: args.no_findings_reason },
          ],
        },
      });
      return {
        content: [
          {
            type: "text",
            text: "Recorded: no findings for this run. Do not call report_insight again; summarize and finish.",
          },
        ],
      };
    }

    // A finding: validate the conditional shape with specific, fixable errors.
    if (!args.observation || !args.evidence || !args.category) {
      return errorResult(
        "A finding requires observation, evidence, and category (or use only no_findings_reason for a clean run).",
      );
    }
    if (existing.some((entry) => "no_findings_reason" in entry)) {
      return errorResult(
        "This run was already reported as having no findings; a finding now is contradictory. Stop reporting.",
      );
    }
    if (existing.length >= MAX_INSIGHTS_PER_RUN) {
      return errorResult(
        `The ${MAX_INSIGHTS_PER_RUN}-finding cap for this run is reached. Stop reporting; summarize what you filed.`,
      );
    }
    if (args.category === "other" && !args.other_justification) {
      return errorResult(
        "category 'other' requires other_justification (50-200 chars).",
      );
    }
    if (
      WASTED_EFFORT_REQUIRED_CATEGORIES.has(args.category) &&
      !args.wasted_effort
    ) {
      return errorResult(
        `category '${args.category}' requires wasted_effort ({metric, amount}).`,
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

    const transcript = await readTranscript(ctx.cwd);
    if (transcript === null) {
      return errorResult(
        `${TRANSCRIPT_FILENAME} was not found in the working directory (or is too large). Run the extractor from the analyzing-task-runs skill first; evidence is verified against that file.`,
      );
    }
    const normalizedTranscript = normalizeForMatch(transcript);
    for (const [index, item] of args.evidence.entries()) {
      if (!normalizedTranscript.includes(normalizeForMatch(item.quote))) {
        return errorResult(
          `evidence[${index}].quote was not found in ${TRANSCRIPT_FILENAME} — copy the text exactly as it appears in the transcript, not from memory.`,
        );
      }
    }

    const insight: StoredInsight = {
      schema_version: 1,
      observation: args.observation,
      evidence: args.evidence,
      occurrence_count: args.occurrence_count ?? 1,
      category: args.category,
      ...(args.other_justification && {
        other_justification: args.other_justification,
      }),
      ...(args.wasted_effort && { wasted_effort: args.wasted_effort }),
      recurrence: args.recurrence,
      confidence_basis: args.confidence_basis,
      suggested_fix: args.suggested_fix,
      reported_at: new Date().toISOString(),
    };
    await client.updateTaskRun(ctx.taskId, ctx.taskRunId, {
      state: { [INSIGHTS_STATE_KEY]: [...existing, insight] },
    });

    const remaining = MAX_INSIGHTS_PER_RUN - existing.length - 1;
    return {
      content: [
        {
          type: "text",
          text: `Recorded finding ${existing.length + 1} (${args.category}). ${remaining} more allowed; only report findings that clear the evidence bar.`,
        },
      ],
    };
  },
});
