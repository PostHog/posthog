/**
 * Runs a saved agent flow (an ordered sequence of role-based subagent steps)
 * inside a pi session. The `agent-flow-run` command validates its payload and
 * returns immediately; the flow itself executes in the background so the
 * initial prompt RPC resolves within pi's 30s response timeout instead of
 * blocking for the whole run. Progress streams to the session as
 * `posthog-agent-flow` custom messages, which the desktop translator turns
 * into chat output and turn-completion signals.
 */
import type {
  ExtensionAPI,
  ExtensionCommandContext,
  ExtensionFactory,
} from "@earendil-works/pi-coding-agent";
import {
  AGENT_FLOW_MESSAGE_TYPE,
  type AgentFlowDefinition,
  type AgentFlowMessageDetails,
  type AgentFlowRole,
  type AgentFlowRunPayload,
  parseAgentFlowRespondArgs,
  parseAgentFlowRunPayload,
} from "@posthog/shared";
import { findBundledAgent } from "../subagent/agents";
import { truncateForModel } from "../subagent/format";
import { setFlowInputRouter } from "./flow-input";
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
  reason?: string;
  aborted?: boolean;
}

interface ActiveFlow {
  flow: AgentFlowDefinition;
  controller: AbortController;
  pendingGuidance: string[];
  /** Steers the step that is running right now, when one is. */
  steerCurrentStep: ((text: string) => void) | null;
  currentStepName: string | null;
  pendingApprovals: Map<string, (response: ApprovalResponse) => void>;
  awaitApproval(approvalId: string): Promise<ApprovalResponse>;
}

export interface AgentFlowExtensionOptions {
  /** Test seam: replaces the in-process step runner. */
  runStep?: RunStepFn;
}

function flowMessage(
  flow: AgentFlowDefinition,
  content: string,
  details: Omit<AgentFlowMessageDetails, "flowId" | "flowName">,
): SendMessageInput {
  return {
    customType: AGENT_FLOW_MESSAGE_TYPE,
    // Consecutive custom messages merge into one chat bubble downstream, so
    // every message carries its own paragraph separator.
    content: `${content}\n\n`,
    display: true,
    details: { flowId: flow.id, flowName: flow.name, ...details },
  };
}

const CHANNEL_CONTEXT_PATTERN = /<channel_context[\s\S]*?<\/channel_context>/g;

function quoted(text: string, cap: number): string {
  // The task creation saga appends a machine-facing channel-context block to
  // the prompt; keep it out of the quote a person reads.
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

/** The last <handoff> block wins; without one, the whole output is the handoff. */
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
  if (guidance.length > 0) {
    parts.push(
      `The user sent additional guidance while the flow was running:\n${guidance
        .map((item) => `- ${item}`)
        .join("\n")}`,
    );
  }
  parts.push(
    isLastStep
      ? "You are the last step. End your reply with the final result for the user inside <handoff></handoff> tags."
      : "End your reply with a compact handoff for the next step inside <handoff></handoff> tags: decisions made, files changed, and open questions.",
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

async function executeFlow(options: {
  pi: ExtensionAPI;
  ctx: ExtensionCommandContext;
  flow: AgentFlowDefinition;
  prompt: string;
  active: ActiveFlow;
  runStep: RunStepFn;
}): Promise<void> {
  const { pi, ctx, flow, prompt, active, runStep } = options;
  const flowStartedAt = Date.now();
  let handoff: string | null = null;
  let currentStepIndex = 0;

  try {
    for (const [stepIndex, step] of flow.steps.entries()) {
      currentStepIndex = stepIndex;
      const baseAgent = findBundledAgent(ROLE_AGENT_NAMES[step.role]);
      if (!baseAgent) {
        throw new Error(`The ${step.role} agent is not available.`);
      }

      const stepDetails = {
        status: "running" as const,
        stepIndex,
        stepCount: flow.steps.length,
        stepName: step.name,
      };
      const guidance = active.pendingGuidance.splice(0);
      const stepPrompt = stepTask(flow, stepIndex, prompt, handoff, guidance);
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
        let result = handle.result;
        const finishStep = (stepResult: typeof result): string => {
          const output = truncateForModel(stepResult.output);
          if (stepResult.failed) {
            throw new Error(
              `${step.name} failed: ${stepResult.errorMessage ?? output ?? "no output"}`,
            );
          }
          const stepHandoff = extractHandoff(output);
          pi.sendMessage(
            flowMessage(
              flow,
              `${stepHandoff}\n\n_${step.name} finished in ${formatDuration(Date.now() - stepStartedAt)}._`,
              { ...stepDetails, event: "step_finished" },
            ),
          );
          return stepHandoff;
        };

        handoff = finishStep(result);

        if (step.approvalAfter && stepIndex < flow.steps.length - 1) {
          let attempt = 0;
          for (;;) {
            const approvalId = `${flow.id}:${stepIndex}:${attempt}`;
            pi.sendMessage(
              flowMessage(flow, handoff ?? "", {
                ...stepDetails,
                event: "approval_requested",
                approvalId,
              }),
            );
            const response = await active.awaitApproval(approvalId);
            if (response.aborted) {
              throw new Error("The flow was stopped.");
            }
            pi.sendMessage(
              flowMessage(
                flow,
                response.approved
                  ? `${step.name} handoff approved.`
                  : `${step.name} handoff sent back for changes${response.reason ? `:\n\n> ${response.reason}` : "."}`,
                {
                  ...stepDetails,
                  event: "approval_resolved",
                  approvalId,
                  approvalOutcome: response.approved ? "approved" : "rejected",
                },
              ),
            );
            if (response.approved) {
              break;
            }
            attempt += 1;
            pi.sendMessage(
              flowMessage(flow, `**${step.name}** is revising the handoff.`, {
                ...stepDetails,
                event: "step_revising",
              }),
            );
            result = await handle.revise(
              [
                "The user reviewed your handoff and requested changes.",
                response.reason
                  ? `Their feedback:\n${response.reason}`
                  : "They did not give a reason; reconsider your handoff critically.",
                "Rework it and end your reply with the revised handoff inside <handoff></handoff> tags.",
              ].join("\n\n"),
            );
            handoff = finishStep(result);
          }
        }
      } finally {
        active.steerCurrentStep = null;
        active.currentStepName = null;
        handle.dispose();
      }
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

  return (pi: ExtensionAPI) => {
    let active: ActiveFlow | null = null;

    pi.on("session_shutdown", () => {
      active?.controller.abort();
      active = null;
      setFlowInputRouter(null);
    });

    // "steer" reaches the running step now; "followUp" waits for the next
    // step. Prompts land here through the input event; steer/follow-up
    // commands land through the rpc host's flow-input router.
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
          reason: payload.reason,
        });
      },
    });

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

        if (active) {
          ctx.ui.notify(
            "A flow is already running in this task. Wait for it to finish or stop the task.",
            "warning",
          );
          return;
        }

        const { flow, prompt } = payload;
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
                resolve({ approved: false, aborted: true });
                return;
              }
              pendingApprovals.set(approvalId, resolve);
              controller.signal.addEventListener(
                "abort",
                () => {
                  if (pendingApprovals.delete(approvalId)) {
                    resolve({ approved: false, aborted: true });
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

        // Intentionally not awaited: the command handler must return before
        // pi acknowledges the prompt RPC, or the whole flow runs inside the
        // request and trips the client's response timeout.
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
      },
    });
  };
}

export default createAgentFlowExtension();
