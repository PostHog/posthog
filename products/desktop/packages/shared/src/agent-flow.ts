import { z } from "zod";

export const AGENT_FLOW_ROLES = [
  "researcher",
  "planner",
  "executor",
  "reviewer",
] as const;

export const AGENT_FLOW_EFFORTS = [
  "off",
  "minimal",
  "low",
  "medium",
  "high",
  "xhigh",
  "max",
] as const;

export type AgentFlowRole = (typeof AGENT_FLOW_ROLES)[number];
export type AgentFlowEffort = (typeof AGENT_FLOW_EFFORTS)[number];

export interface AgentFlowModel {
  provider: "posthog";
  id: string;
  name: string;
}

export interface AgentFlowStep {
  id: string;
  name: string;
  role: AgentFlowRole;
  model: AgentFlowModel;
  effort: AgentFlowEffort;
  approvalAfter: boolean;
  instructions?: string;
}

export interface AgentFlowDefinition {
  id: string;
  name: string;
  steps: AgentFlowStep[];
}

const agentFlowModelSchema = z.object({
  provider: z.literal("posthog"),
  id: z.string().min(1),
  name: z.string().min(1),
});

const agentFlowStepSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  role: z.enum(AGENT_FLOW_ROLES),
  model: agentFlowModelSchema,
  effort: z.enum(AGENT_FLOW_EFFORTS),
  approvalAfter: z.boolean(),
  instructions: z.string().optional(),
});

export const agentFlowDefinitionSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  steps: z.array(agentFlowStepSchema).min(2).max(6),
});

export const agentFlowRunPayloadSchema = z.object({
  flow: agentFlowDefinitionSchema,
  prompt: z.string().min(1),
});

export type AgentFlowRunPayload = z.infer<typeof agentFlowRunPayloadSchema>;

export const AGENT_FLOW_MESSAGE_TYPE = "posthog-agent-flow";

export const AGENT_FLOW_HANDOFF_TOOL = "submit_handoff";

export const agentFlowHandoffSchema = z.object({
  stepIndex: z.number().int().nonnegative(),
  stepName: z.string().min(1),
  title: z.string().min(1),
  artifactName: z.string().min(1),
  version: z.number().int().positive(),
  markdown: z.string(),
});

export type AgentFlowHandoff = z.infer<typeof agentFlowHandoffSchema>;

export const agentFlowReviewCommentSchema = z.object({
  quote: z.string().optional(),
  body: z.string().min(1),
});

export const agentFlowReviewSchema = z.object({
  note: z.string().optional(),
  comments: z.array(agentFlowReviewCommentSchema).default([]),
});

export type AgentFlowReviewComment = z.infer<
  typeof agentFlowReviewCommentSchema
>;
export type AgentFlowReview = z.infer<typeof agentFlowReviewSchema>;

export function isEmptyAgentFlowReview(review: AgentFlowReview): boolean {
  return !review.note?.trim() && review.comments.length === 0;
}

export function formatAgentFlowReview(review: AgentFlowReview): string {
  const parts: string[] = [];
  if (review.note?.trim()) {
    parts.push(review.note.trim());
  }
  for (const [index, comment] of review.comments.entries()) {
    const lines = [`${index + 1}. ${comment.body.trim()}`];
    if (comment.quote?.trim()) {
      lines.push(
        ...comment.quote
          .trim()
          .split("\n")
          .map((line) => `   > ${line}`),
      );
    }
    parts.push(lines.join("\n"));
  }
  return parts.join("\n\n");
}

export const AGENT_FLOW_MESSAGE_STATUSES = [
  "running",
  "completed",
  "stopped",
  "failed",
] as const;

export const AGENT_FLOW_MESSAGE_EVENTS = [
  "flow_started",
  "step_started",
  "step_finished",
  "step_revising",
  "approval_requested",
  "approval_resolved",
  "guidance",
  "flow_completed",
  "flow_stopped",
  "flow_failed",
] as const;

export const agentFlowMessageDetailsSchema = z.object({
  flowId: z.string().min(1),
  flowName: z.string().min(1),
  status: z.enum(AGENT_FLOW_MESSAGE_STATUSES),
  event: z.enum(AGENT_FLOW_MESSAGE_EVENTS).optional(),
  stepIndex: z.number().int().nonnegative().optional(),
  stepCount: z.number().int().positive().optional(),
  stepName: z.string().optional(),
  approvalId: z.string().optional(),
  approvalOutcome: z.enum(["approved", "rejected"]).optional(),
  stepPrompt: z.string().optional(),
  handoff: agentFlowHandoffSchema.optional(),
  review: agentFlowReviewSchema.optional(),
});

export type AgentFlowMessageStatus =
  (typeof AGENT_FLOW_MESSAGE_STATUSES)[number];
export type AgentFlowMessageDetails = z.infer<
  typeof agentFlowMessageDetailsSchema
>;

export function isAgentFlowTerminalStatus(
  status: AgentFlowMessageStatus,
): boolean {
  return status !== "running";
}

export const AGENT_FLOW_STEP_CARD_ID_PREFIX = "agent-flow:";

export function agentFlowStepCardId(flowId: string, stepIndex: number): string {
  return `${AGENT_FLOW_STEP_CARD_ID_PREFIX}${flowId}:${stepIndex}`;
}

const STEP_CARD_ID_PATTERN = /^agent-flow:[^:]+:\d+$/;

export function isAgentFlowStepCardId(id: string | undefined): boolean {
  return id !== undefined && STEP_CARD_ID_PATTERN.test(id);
}

export function isAgentFlowCardId(id: string | undefined): boolean {
  return isAgentFlowStepCardId(id) || isAgentFlowApprovalCardId(id);
}

export function agentFlowApprovalCardId(
  flowId: string,
  approvalId: string,
): string {
  return `${AGENT_FLOW_STEP_CARD_ID_PREFIX}${flowId}:approval:${approvalId}`;
}

export function isAgentFlowApprovalCardId(id: string | undefined): boolean {
  return (
    id?.startsWith(AGENT_FLOW_STEP_CARD_ID_PREFIX) === true &&
    id.includes(":approval:")
  );
}

export function buildAgentFlowRespondCommand(
  approvalId: string,
  outcome: "approve" | "reject",
  review?: AgentFlowReview,
): string {
  const encoded =
    review && !isEmptyAgentFlowReview(review)
      ? ` ${encodeURIComponent(JSON.stringify(review))}`
      : "";
  return `/agent-flow-respond ${encodeURIComponent(approvalId)} ${outcome}${encoded}`;
}

export interface AgentFlowRespondPayload {
  approvalId: string;
  outcome: "approve" | "reject";
  review: AgentFlowReview;
}

/** Reads the review, or the plain-text reason older sessions still carry. */
function parseReviewArgument(raw: string | undefined): AgentFlowReview {
  const trimmed = raw?.trim();
  if (!trimmed) {
    return { comments: [] };
  }
  let decoded = trimmed;
  try {
    decoded = decodeURIComponent(trimmed);
  } catch {
    // A legacy reason may hold a stray percent sign.
  }
  if (decoded.startsWith("{")) {
    try {
      const parsed = agentFlowReviewSchema.safeParse(JSON.parse(decoded));
      if (parsed.success) {
        return parsed.data;
      }
    } catch {
      // Fall through to the plain-text reading.
    }
  }
  return { note: decoded, comments: [] };
}

export function parseAgentFlowRespondArgs(
  args: string,
): AgentFlowRespondPayload | undefined {
  const match = args
    .trim()
    .match(/^(\S+)\s+(approve|reject)(?:\s+([\s\S]+))?$/);
  if (!match) {
    return undefined;
  }
  return {
    approvalId: decodeURIComponent(match[1]),
    outcome: match[2] as "approve" | "reject",
    review: parseReviewArgument(match[3]),
  };
}

export const AGENT_FLOW_STEP_EVENT_TYPE = "posthog_flow_step_event";

export const agentFlowStepStreamEventSchema = z.object({
  type: z.literal(AGENT_FLOW_STEP_EVENT_TYPE),
  flowId: z.string().min(1),
  stepIndex: z.number().int().nonnegative(),
  timestamp: z.number(),
  event: z.discriminatedUnion("kind", [
    z.object({
      kind: z.literal("tool_start"),
      toolCallId: z.string().min(1),
      toolName: z.string().min(1),
      title: z.string().optional(),
      path: z.string().optional(),
      diff: z
        .object({
          path: z.string(),
          oldText: z.string().nullable().optional(),
          newText: z.string(),
        })
        .optional(),
    }),
    z.object({
      kind: z.literal("tool_end"),
      toolCallId: z.string().min(1),
      toolName: z.string().min(1),
      isError: z.boolean().optional(),
      outputPreview: z.string().optional(),
    }),
    z.object({
      kind: z.literal("assistant_text"),
      text: z.string(),
    }),
  ]),
});

export type AgentFlowStepStreamEvent = z.infer<
  typeof agentFlowStepStreamEventSchema
>;

export function buildAgentFlowRunCommand(
  flow: AgentFlowDefinition,
  prompt: string,
): string {
  return `/agent-flow-run ${encodeURIComponent(JSON.stringify({ flow, prompt }))}`;
}

export function parseAgentFlowRunPayload(value: string): AgentFlowRunPayload {
  return agentFlowRunPayloadSchema.parse(JSON.parse(decodeURIComponent(value)));
}

export const AGENT_FLOW_SKILL_FILE = "flow.json";

export function parseAgentFlowSkillFile(
  content: string,
): AgentFlowDefinition | null {
  try {
    return agentFlowDefinitionSchema.parse(JSON.parse(content));
  } catch {
    return null;
  }
}

export function serializeAgentFlowSkillFile(flow: AgentFlowDefinition): string {
  return `${JSON.stringify(flow, null, 2)}\n`;
}

export function agentFlowSkillSlug(name: string): string {
  const slug = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64)
    .replace(/-+$/g, "");
  return slug || "flow";
}

/** Stable across revisions, so every revision lands as a new version of one artifact. */
export function agentFlowHandoffArtifactName(
  flowName: string,
  stepIndex: number,
  stepName: string,
): string {
  return `${agentFlowSkillSlug(flowName)}-step-${stepIndex + 1}-${agentFlowSkillSlug(stepName)}.md`;
}

export function buildAgentFlowSkillDescription(
  flow: AgentFlowDefinition,
): string {
  const chain = flow.steps.map((step) => step.name).join(", then ");
  return `Multi-agent flow: ${chain}. Use when the user asks to run the "${flow.name}" flow.`;
}

export function buildAgentFlowSkillBody(flow: AgentFlowDefinition): string {
  const steps = flow.steps
    .map((step, index) => {
      const lines = [
        `${index + 1}. **${step.name}** (${step.role}) — model \`${step.model.name}\`, effort ${step.effort}.`,
      ];
      if (step.instructions) {
        lines.push(`   Instructions: ${step.instructions}`);
      }
      if (step.approvalAfter) {
        lines.push(
          "   Stop after this step. Show the handoff and wait for the user to approve it before you continue.",
        );
      }
      return lines.join("\n");
    })
    .join("\n");
  return `This is a saved agent flow. The machine-readable definition is in [flow.json](flow.json).

If the \`run_agent_flow\` tool is available, call it now with \`name: "${agentFlowSkillSlug(flow.name)}"\` and the user's task stated in full, then end your turn. The flow runs each step as its own agent session and reports back in this chat. Do not run the steps yourself.

Only if the \`run_agent_flow\` tool is not available, run the task as a sequence of steps yourself, in order. Each step is one focused agent turn. Pass each step's result to the next step as its input.

## Steps

${steps}
`;
}
