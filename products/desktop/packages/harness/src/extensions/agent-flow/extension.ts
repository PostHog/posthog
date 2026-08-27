import {
  defineTool,
  type ExtensionAPI,
  type ExtensionCommandContext,
  type ExtensionContext,
  type ExtensionFactory,
} from "@earendil-works/pi-coding-agent";
import {
  AGENT_FLOW_HANDOFF_TOOL,
  AGENT_FLOW_MESSAGE_TYPE,
  type AgentFlowDefinition,
  type AgentFlowHandoff,
  type AgentFlowMessageDetails,
  type AgentFlowReview,
  type AgentFlowRole,
  type AgentFlowRunPayload,
  agentFlowHandoffArtifactName,
  formatAgentFlowReview,
  isEmptyAgentFlowReview,
  parseAgentFlowRespondArgs,
  parseAgentFlowRunPayload,
} from "@posthog/shared";
import { Type } from "typebox";
import { findBundledAgent } from "../subagent/agents";
import { truncateForModel } from "../subagent/format";
import { setFlowInputRouter } from "./flow-input";
import { findFlowSkill, listFlowSkills } from "./flow-skills";
import { HANDOFF_GUIDANCE, HANDOFF_REMINDER } from "./handoff";
import { emitFlowStepEvent } from "./step-events";
import { runStepSession as defaultRunStepSession } from "./step-session";

type SendMessageInput = Parameters<ExtensionAPI["sendMessage"]>[0];
type RunStepFn = typeof defaultRunStepSession;

const ROLE_AGENT_NAMES: Record<AgentFlowRole, string> = {
  researcher: "Explore",
  planner: "Plan",
  executor: "General",
  reviewer: "Review",
};

const PROMPT_QUOTE_CAP = 1_500;
const HANDOFF_PATTERN = /<handoff>([\s\S]*?)<\/handoff>/g;

interface ApprovalResponse {
  approved: boolean;
  review: AgentFlowReview;
  aborted?: boolean;
}

const NO_REVIEW: AgentFlowReview = { comments: [] };

interface ActiveFlow {
  flow: AgentFlowDefinition;
  controller: AbortController;
  pendingGuidance: string[];
  steerCurrentStep: ((text: string) => void) | null;
  currentStepName: string | null;
  pendingApprovals: Map<string, (response: ApprovalResponse) => void>;
  awaitApproval(approvalId: string): Promise<ApprovalResponse>;
}

export interface AgentFlowExtensionOptions {
  runStep?: RunStepFn;
  findFlow?: typeof findFlowSkill;
  listFlows?: typeof listFlowSkills;
}

function flowMessage(
  flow: AgentFlowDefinition,
  content: string,
  details: Omit<AgentFlowMessageDetails, "flowId" | "flowName">,
): SendMessageInput {
  return {
    customType: AGENT_FLOW_MESSAGE_TYPE,
    content: `${content}\n\n`,
    display: true,
    details: { flowId: flow.id, flowName: flow.name, ...details },
  };
}

const CHANNEL_CONTEXT_PATTERN = /<channel_context[\s\S]*?<\/channel_context>/g;

function quoted(text: string, cap: number): string {
  const trimmed = text.replace(CHANNEL_CONTEXT_PATTERN, "").trim();
  const capped = trimmed.length > cap ? `${trimmed.slice(0, cap)}…` : trimmed;
  return capped
    .split("\n")
    .map((line) => `> ${line}`)
    .join("\n");
}

function formatDuration(ms: number): string {
  const totalSeconds = Math.max(1, Math.round(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`;
}

export function extractHandoff(output: string): string {
  let last: string | undefined;
  for (const match of output.matchAll(HANDOFF_PATTERN)) {
    last = match[1];
  }
  const text = last?.trim();
  return text ? text : output.trim();
}

export function stepTask(
  flow: AgentFlowDefinition,
  stepIndex: number,
  prompt: string,
  handoff: string | null,
  guidance: string[],
  review?: AgentFlowReview,
): string {
  const step = flow.steps[stepIndex];
  const isLastStep = stepIndex === flow.steps.length - 1;
  const parts = [
    `You are "${step.name}", step ${stepIndex + 1} of ${flow.steps.length} in the "${flow.name}" flow.`,
    `User task:\n${prompt}`,
  ];
  if (step.instructions?.trim()) {
    parts.push(`Step instructions:\n${step.instructions.trim()}`);
  }
  if (handoff) {
    parts.push(`Handoff from the prior step:\n${handoff}`);
  }
  if (review && !isEmptyAgentFlowReview(review)) {
    parts.push(
      `The user approved that handoff with comments. Act on them:\n${formatAgentFlowReview(review)}`,
    );
  }
  if (guidance.length > 0) {
    parts.push(
      `The user sent additional guidance while the flow was running:\n${guidance
        .map((item) => `- ${item}`)
        .join("\n")}`,
    );
  }
  parts.push(
    isLastStep
      ? `End your turn by calling the ${AGENT_FLOW_HANDOFF_TOOL} tool with the final result for the user.`
      : `End your turn by calling the ${AGENT_FLOW_HANDOFF_TOOL} tool with your handoff for the next step.`,
    HANDOFF_GUIDANCE,
    `If the ${AGENT_FLOW_HANDOFF_TOOL} tool is not available, end your reply with the same document inside <handoff></handoff> tags.`,
  );
  return parts.join("\n\n");
}

function startMessage(
  flow: AgentFlowDefinition,
  prompt: string,
): SendMessageInput {
  const stepNames = flow.steps.map((step) => step.name).join(" → ");
  return flowMessage(
    flow,
    `**${flow.name}** flow started.\n\n${quoted(prompt, PROMPT_QUOTE_CAP)}\n\nSteps: ${stepNames}`,
    { status: "running", event: "flow_started", stepCount: flow.steps.length },
  );
}

/** What one finished step hands to the next: its document and the review of it. */
interface StepOutcome {
  handoff: AgentFlowHandoff;
  review: AgentFlowReview;
}

async function executeStep(options: {
  pi: ExtensionAPI;
  ctx: ExtensionContext;
  flow: AgentFlowDefinition;
  prompt: string;
  active: ActiveFlow;
  runStep: RunStepFn;
  stepIndex: number;
  previous: StepOutcome | null;
}): Promise<StepOutcome> {
  const { pi, ctx, flow, prompt, active, runStep, stepIndex, previous } =
    options;
  const step = flow.steps[stepIndex];
  const baseAgent = findBundledAgent(ROLE_AGENT_NAMES[step.role]);
  if (!baseAgent) {
    throw new Error(`The ${step.role} agent is not available.`);
  }

  const stepDetails = {
    status: "running" as const,
    stepIndex,
    stepCount: flow.steps.length,
    stepName: step.name,
    stepModel: step.model.name,
  };
  const guidance = active.pendingGuidance.splice(0);
  const stepPrompt = stepTask(
    flow,
    stepIndex,
    prompt,
    previous?.handoff.markdown ?? null,
    guidance,
    previous?.review,
  );
  pi.sendMessage(
    flowMessage(
      flow,
      `**Step ${stepIndex + 1} of ${flow.steps.length}: ${step.name}** (${step.model.name}, ${step.effort} effort)`,
      {
        ...stepDetails,
        event: "step_started",
        stepPrompt: stepPrompt.slice(0, 8_000),
      },
    ),
  );

  const stepStartedAt = Date.now();
  let handle: Awaited<ReturnType<RunStepFn>>;
  try {
    handle = await runStep({
      ctx,
      agent: { ...baseAgent, name: step.name },
      model: { provider: step.model.provider, id: step.model.id },
      thinkingLevel: step.effort,
      task: stepPrompt,
      signal: active.controller.signal,
      onStreamEvent: (event) =>
        emitFlowStepEvent({
          type: "posthog_flow_step_event",
          flowId: flow.id,
          stepIndex,
          timestamp: Date.now(),
          event,
        }),
      onSteerAvailable: (steer) => {
        active.steerCurrentStep = steer;
        active.currentStepName = step.name;
      },
    });
  } catch (error) {
    active.steerCurrentStep = null;
    active.currentStepName = null;
    throw error;
  }

  try {
    let version = 0;
    const artifactName = agentFlowHandoffArtifactName(
      flow.name,
      stepIndex,
      step.name,
    );
    const finishStep = (stepResult: typeof handle.result): AgentFlowHandoff => {
      const output = truncateForModel(stepResult.output);
      if (stepResult.failed) {
        throw new Error(
          `${step.name} failed: ${stepResult.errorMessage ?? output ?? "no output"}`,
        );
      }
      const submission = handle.peekHandoff?.() ?? null;
      version += 1;
      const stepHandoff: AgentFlowHandoff = {
        stepIndex,
        stepName: step.name,
        title: submission?.title ?? step.name,
        artifactName,
        version,
        markdown: submission?.markdown ?? extractHandoff(output),
      };
      pi.sendMessage(
        flowMessage(
          flow,
          `${stepHandoff.markdown}\n\n_${step.name} finished in ${formatDuration(Date.now() - stepStartedAt)}._`,
          { ...stepDetails, event: "step_finished", handoff: stepHandoff },
        ),
      );
      return stepHandoff;
    };

    let result = handle.result;
    // One deterministic nudge for a step that ignored the tool.
    if (!result.failed && handle.peekHandoff && !handle.peekHandoff()) {
      result = await handle.revise(HANDOFF_REMINDER);
    }
    let handoff = finishStep(result);

    if (!step.approvalAfter || stepIndex === flow.steps.length - 1) {
      return { handoff, review: NO_REVIEW };
    }

    for (let attempt = 0; ; attempt += 1) {
      const approvalId = `${flow.id}:${stepIndex}:${attempt}`;
      pi.sendMessage(
        flowMessage(flow, `Review the **${step.name}** handoff.`, {
          ...stepDetails,
          event: "approval_requested",
          approvalId,
          handoff,
        }),
      );
      const response = await active.awaitApproval(approvalId);
      if (response.aborted) {
        throw new Error("The flow was stopped.");
      }
      const hasReview = !isEmptyAgentFlowReview(response.review);
      const commentCount = response.review.comments.length;
      const withComments =
        commentCount > 0
          ? ` with ${commentCount} comment${commentCount === 1 ? "" : "s"}`
          : "";
      pi.sendMessage(
        flowMessage(
          flow,
          response.approved
            ? `${step.name} handoff approved${withComments}.`
            : `${step.name} handoff sent back for changes${withComments}.`,
          {
            ...stepDetails,
            event: "approval_resolved",
            approvalId,
            approvalOutcome: response.approved ? "approved" : "rejected",
            handoff,
            ...(hasReview ? { review: response.review } : {}),
          },
        ),
      );
      if (response.approved) {
        return { handoff, review: response.review };
      }
      pi.sendMessage(
        flowMessage(flow, `**${step.name}** is revising the handoff.`, {
          ...stepDetails,
          event: "step_revising",
        }),
      );
      result = await handle.revise(
        [
          "The user reviewed your handoff and asked for changes.",
          hasReview
            ? `Their review:\n${formatAgentFlowReview(response.review)}`
            : "They did not say what to change; reconsider your handoff critically.",
          `Rework the document and submit the new version with the ${AGENT_FLOW_HANDOFF_TOOL} tool.`,
        ].join("\n\n"),
      );
      handoff = finishStep(result);
    }
  } finally {
    active.steerCurrentStep = null;
    active.currentStepName = null;
    handle.dispose();
  }
}

async function executeFlow(options: {
  pi: ExtensionAPI;
  ctx: ExtensionContext;
  flow: AgentFlowDefinition;
  prompt: string;
  active: ActiveFlow;
  runStep: RunStepFn;
}): Promise<void> {
  const { pi, ctx, flow, prompt, active, runStep } = options;
  const flowStartedAt = Date.now();
  let currentStepIndex = 0;

  try {
    let previous: StepOutcome | null = null;
    for (const stepIndex of flow.steps.keys()) {
      currentStepIndex = stepIndex;
      previous = await executeStep({
        pi,
        ctx,
        flow,
        prompt,
        active,
        runStep,
        stepIndex,
        previous,
      });
    }

    pi.sendMessage(
      flowMessage(
        flow,
        `**${flow.name}** finished in ${formatDuration(Date.now() - flowStartedAt)}.`,
        {
          status: "completed",
          event: "flow_completed",
          stepCount: flow.steps.length,
        },
      ),
    );
  } catch (error) {
    if (active.controller.signal.aborted) {
      pi.sendMessage(
        flowMessage(flow, `**${flow.name}** was stopped.`, {
          status: "stopped",
          event: "flow_stopped",
          stepIndex: currentStepIndex,
          stepCount: flow.steps.length,
        }),
      );
      return;
    }
    const message = error instanceof Error ? error.message : "The flow failed.";
    pi.sendMessage(
      flowMessage(flow, `**${flow.name}** failed.\n\n${message}`, {
        status: "failed",
        event: "flow_failed",
        stepIndex: currentStepIndex,
        stepCount: flow.steps.length,
      }),
    );
  }
}

export function createAgentFlowExtension(
  options: AgentFlowExtensionOptions = {},
): ExtensionFactory {
  const runStep = options.runStep ?? defaultRunStepSession;
  const findFlow = options.findFlow ?? findFlowSkill;
  const listFlows = options.listFlows ?? listFlowSkills;

  return (pi: ExtensionAPI) => {
    let active: ActiveFlow | null = null;

    pi.on("session_shutdown", () => {
      active?.controller.abort();
      active = null;
      setFlowInputRouter(null);
    });

    const routeFlowInput = (text: string, mode: "steer" | "followUp") => {
      if (!active) return false;
      const steer = mode === "steer" ? active.steerCurrentStep : null;
      if (steer) {
        steer(text);
        pi.sendMessage(
          flowMessage(
            active.flow,
            `${quoted(text, PROMPT_QUOTE_CAP)}\n\nSent to the running step: ${active.currentStepName ?? "current step"}.`,
            { status: "running", event: "guidance" },
          ),
        );
        return true;
      }
      active.pendingGuidance.push(text);
      pi.sendMessage(
        flowMessage(
          active.flow,
          `${quoted(text, PROMPT_QUOTE_CAP)}\n\nYour message will be included in the next step of the flow.`,
          { status: "running", event: "guidance" },
        ),
      );
      return true;
    };

    pi.on("input", (event) => {
      if (!active) return undefined;
      const text = event.text.trim();
      if (!text || text.startsWith("/")) return undefined;
      return routeFlowInput(text, "steer")
        ? { action: "handled" as const }
        : undefined;
    });

    pi.registerCommand("agent-flow-respond", {
      description: "Answer a flow handoff review",
      handler: async (args: string, ctx: ExtensionCommandContext) => {
        const payload = parseAgentFlowRespondArgs(args);
        if (!payload) {
          ctx.ui.notify("The review response is invalid.", "error");
          return;
        }
        const resolve = active?.pendingApprovals.get(payload.approvalId);
        if (!active || !resolve) {
          ctx.ui.notify("This review is no longer waiting.", "warning");
          return;
        }
        active.pendingApprovals.delete(payload.approvalId);
        resolve({
          approved: payload.outcome === "approve",
          review: payload.review,
        });
      },
    });

    const startFlow = (
      flow: AgentFlowDefinition,
      prompt: string,
      ctx: ExtensionContext,
    ): string | null => {
      if (active) {
        return "A flow is already running in this task. Wait for it to finish or stop the task.";
      }

      const controller = new AbortController();
      const pendingApprovals = new Map<
        string,
        (response: ApprovalResponse) => void
      >();
      const current: ActiveFlow = {
        flow,
        controller,
        pendingGuidance: [],
        steerCurrentStep: null,
        currentStepName: null,
        pendingApprovals,
        awaitApproval(approvalId) {
          return new Promise<ApprovalResponse>((resolve) => {
            if (controller.signal.aborted) {
              resolve({ approved: false, review: NO_REVIEW, aborted: true });
              return;
            }
            pendingApprovals.set(approvalId, resolve);
            controller.signal.addEventListener(
              "abort",
              () => {
                if (pendingApprovals.delete(approvalId)) {
                  resolve({
                    approved: false,
                    review: NO_REVIEW,
                    aborted: true,
                  });
                }
              },
              { once: true },
            );
          });
        },
      };
      active = current;
      setFlowInputRouter(routeFlowInput);

      pi.sendMessage(startMessage(flow, prompt));

      // Not awaited: the flow runs in the background so the RPC resolves first.
      void executeFlow({
        pi,
        ctx,
        flow,
        prompt,
        active: current,
        runStep,
      }).finally(() => {
        setFlowInputRouter(null);
        if (active === current) {
          active = null;
        }
      });
      return null;
    };

    pi.registerTool(
      defineTool({
        name: "run_agent_flow",
        label: "Run agent flow",
        description:
          "Run a saved PostHog agent flow: an ordered sequence of subagent steps, each with its own model and reasoning effort. The flow executes deterministically in the background and posts its progress, handoff reviews, and result into this chat. Use it when the user asks to run a saved flow, or when a flow skill tells you to. After it starts, end your turn; do not do the task yourself.",
        parameters: Type.Object({
          name: Type.String({
            description:
              "The flow to run: its skill folder name or display name",
          }),
          task: Type.String({
            description: "The user's task for the flow, stated in full",
          }),
        }),
        async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
          const found = findFlow(params.name, ctx.cwd);
          if (!found) {
            const names = listFlows(ctx.cwd)
              .map((skill) => skill.dirName)
              .join(", ");
            return {
              content: [
                {
                  type: "text" as const,
                  text: `No saved flow matches "${params.name}". ${names ? `Available flows: ${names}.` : "There are no saved flows."}`,
                },
              ],
              details: {},
            };
          }
          const error = startFlow(found.flow, params.task, ctx);
          if (error) {
            return {
              content: [{ type: "text" as const, text: error }],
              details: {},
            };
          }
          const chain = found.flow.steps.map((step) => step.name).join(" -> ");
          return {
            content: [
              {
                type: "text" as const,
                text: `Started the "${found.flow.name}" flow (${chain}). Each step runs as its own agent session with its configured model and effort; progress and reviews appear in this chat. End your turn now.`,
              },
            ],
            details: {},
          };
        },
      }),
    );

    pi.registerCommand("agent-flow-run", {
      description: "Run a saved PostHog agent flow",
      handler: async (args: string, ctx: ExtensionCommandContext) => {
        let payload: AgentFlowRunPayload;
        try {
          payload = parseAgentFlowRunPayload(args.trim());
        } catch (error) {
          ctx.ui.notify(
            error instanceof Error
              ? error.message
              : "The agent flow is invalid.",
            "error",
          );
          return;
        }

        const refusal = startFlow(payload.flow, payload.prompt, ctx);
        if (refusal) {
          ctx.ui.notify(refusal, "warning");
        }
      },
    });
  };
}

export default createAgentFlowExtension();
