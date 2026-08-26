/**
 * Runs one flow step as an in-process pi session — the pattern the pi
 * subagent ecosystem converged on (see tintinweb/pi-subagents): no child
 * process, and the parent's model runtime and auth are shared directly. The
 * step persists as a real pi session parented to the flow's session, so its
 * full transcript stays inspectable.
 */
import {
  type AgentSession,
  createAgentSession,
  DefaultResourceLoader,
  type ExtensionContext,
  getAgentDir,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";
import type { AgentConfig } from "../subagent/agents";

/** Steer the model to wrap up at the soft cap; hard-abort a few turns later. */
const MAX_STEP_TURNS = 80;
const GRACE_TURNS = 5;
const TOOL_OUTPUT_PREVIEW_CAP = 2_000;

/** Display-only stream of a step's work, forwarded to the parent session. */
export type StepStreamEvent =
  | {
      kind: "tool_start";
      toolCallId: string;
      toolName: string;
      title?: string;
    }
  | {
      kind: "tool_end";
      toolCallId: string;
      toolName: string;
      isError?: boolean;
      outputPreview?: string;
    }
  | { kind: "assistant_text"; text: string };

/** The slice of extension context the runner needs; both `ExtensionContext`
 * and `ExtensionCommandContext` satisfy it. */
export interface StepSessionContext {
  cwd: string;
  modelRegistry: ExtensionContext["modelRegistry"];
  sessionManager?: { getSessionFile?(): string | undefined };
  isProjectTrusted(): boolean;
}

export interface RunStepSessionOptions {
  ctx: StepSessionContext;
  agent: AgentConfig;
  model: { provider: string; id: string };
  thinkingLevel?: string;
  task: string;
  signal: AbortSignal;
  onStreamEvent?: (event: StepStreamEvent) => void;
  /** Receives a steer function while the step runs, so user messages can be
   * routed into the running step. */
  onSteerAvailable?: (steer: (text: string) => void) => void;
}

export interface StepSessionResult {
  output: string;
  failed: boolean;
  errorMessage?: string;
}

export interface StepSessionHandle {
  result: StepSessionResult;
  /** Runs another prompt on the still-open step session. */
  revise(feedback: string): Promise<StepSessionResult>;
  dispose(): void;
}

function summarizeToolInput(toolName: string, args: unknown): string {
  if (args && typeof args === "object") {
    const record = args as Record<string, unknown>;
    const primary =
      record.command ?? record.path ?? record.pattern ?? record.file_path;
    if (typeof primary === "string" && primary.trim()) {
      return `${toolName}: ${primary.trim().slice(0, 120)}`;
    }
  }
  return toolName;
}

function previewToolResult(result: unknown): string | undefined {
  if (typeof result === "string") {
    return result.slice(0, TOOL_OUTPUT_PREVIEW_CAP);
  }
  if (result && typeof result === "object") {
    const content = (result as { content?: unknown }).content;
    if (Array.isArray(content)) {
      const text = content
        .flatMap((block) =>
          block &&
          typeof block === "object" &&
          (block as { type?: string }).type === "text" &&
          typeof (block as { text?: unknown }).text === "string"
            ? [(block as { text: string }).text]
            : [],
        )
        .join("\n");
      if (text) {
        return text.slice(0, TOOL_OUTPUT_PREVIEW_CAP);
      }
    }
  }
  return undefined;
}

function assistantText(message: unknown): string {
  const candidate = message as {
    role?: string;
    content?: Array<{ type?: string; text?: string }>;
  };
  if (candidate.role !== "assistant" || !Array.isArray(candidate.content)) {
    return "";
  }
  return candidate.content
    .flatMap((block) =>
      block.type === "text" && typeof block.text === "string"
        ? [block.text]
        : [],
    )
    .join("\n")
    .trim();
}

function lastAssistantText(session: AgentSession, startIndex: number): string {
  let text = "";
  for (const message of session.messages.slice(startIndex)) {
    if (message.role !== "assistant" || !Array.isArray(message.content)) {
      continue;
    }
    const blocks = message.content
      .flatMap((block) => (block.type === "text" ? [block.text] : []))
      .join("\n")
      .trim();
    if (blocks) {
      text = blocks;
    }
  }
  return text;
}

function lastAssistantError(
  session: AgentSession,
  startIndex: number,
): string | undefined {
  for (const message of session.messages.slice(startIndex).reverse()) {
    if (message.role !== "assistant") {
      continue;
    }
    if (message.stopReason === "error") {
      return message.errorMessage ?? "The step failed.";
    }
    return undefined;
  }
  return undefined;
}

export async function runStepSession(
  options: RunStepSessionOptions,
): Promise<StepSessionHandle> {
  const { ctx, agent, task, signal } = options;

  const model = ctx.modelRegistry.find(
    options.model.provider,
    options.model.id,
  );
  if (!model) {
    throw new Error(
      `Model "${options.model.provider}/${options.model.id}" is not available.`,
    );
  }

  const agentDir = getAgentDir();
  const persona = agent.systemPrompt.trim();
  const loader = new DefaultResourceLoader({
    cwd: ctx.cwd,
    agentDir,
    // Steps are single-purpose personas: no ambient extensions or slash
    // surfaces. Skills and project context files stay available.
    noExtensions: true,
    noPromptTemplates: true,
    noThemes: true,
    ...(persona ? { systemPromptOverride: () => persona } : {}),
  });
  await loader.reload();

  // The registry is pi's read facade over the runtime that createAgentSession
  // wants; reaching through it is how in-process subagents inherit the
  // parent's providers and auth (same approach as tintinweb/pi-subagents).
  const parentModelRuntime = (
    ctx.modelRegistry as unknown as { runtime?: unknown }
  ).runtime;

  const { session } = await createAgentSession({
    cwd: ctx.cwd,
    agentDir,
    model,
    ...(options.thinkingLevel
      ? { thinkingLevel: options.thinkingLevel as never }
      : {}),
    ...(agent.tools && agent.tools.length > 0 ? { tools: agent.tools } : {}),
    resourceLoader: loader,
    sessionManager: SessionManager.create(ctx.cwd, undefined, {
      parentSession: ctx.sessionManager?.getSessionFile?.() ?? undefined,
    }),
    settingsManager: SettingsManager.create(ctx.cwd, agentDir, {
      projectTrusted: ctx.isProjectTrusted(),
    }),
    ...(parentModelRuntime !== undefined
      ? { modelRuntime: parentModelRuntime as never }
      : {}),
  });
  session.setSessionName(`flow-step:${agent.name}`);

  options.onSteerAvailable?.((text) => void session.steer(text));

  let turnCount = 0;
  let softLimitReached = false;
  let aborted = false;
  const unsubscribe = session.subscribe((event) => {
    if (event.type === "tool_execution_start") {
      options.onStreamEvent?.({
        kind: "tool_start",
        toolCallId: event.toolCallId,
        toolName: event.toolName,
        title: summarizeToolInput(event.toolName, event.args),
      });
      return;
    }
    if (event.type === "tool_execution_end") {
      options.onStreamEvent?.({
        kind: "tool_end",
        toolCallId: event.toolCallId,
        toolName: event.toolName,
        isError: event.isError,
        outputPreview: previewToolResult(event.result),
      });
      return;
    }
    if (event.type === "message_end") {
      const text = assistantText(event.message);
      if (text) {
        options.onStreamEvent?.({ kind: "assistant_text", text });
      }
      return;
    }
    if (event.type !== "turn_end") {
      return;
    }
    turnCount += 1;
    if (!softLimitReached && turnCount >= MAX_STEP_TURNS) {
      softLimitReached = true;
      void session.steer(
        "You have reached your turn limit. Wrap up immediately and provide your final handoff now.",
      );
    } else if (softLimitReached && turnCount >= MAX_STEP_TURNS + GRACE_TURNS) {
      aborted = true;
      void session.abort();
    }
  });

  const onAbort = () => {
    aborted = true;
    void session.abort();
  };
  if (signal.aborted) {
    onAbort();
  } else {
    signal.addEventListener("abort", onAbort, { once: true });
  }

  const runPrompt = async (text: string): Promise<StepSessionResult> => {
    const startIndex = session.messages.length;
    await session.prompt(text);
    const output = lastAssistantText(session, startIndex);
    const errorMessage = lastAssistantError(session, startIndex);
    const failed = aborted || signal.aborted || errorMessage !== undefined;
    return {
      output,
      failed,
      errorMessage: aborted
        ? "The step was stopped."
        : (errorMessage ?? (failed ? "The step failed." : undefined)),
    };
  };

  const dispose = () => {
    unsubscribe();
    signal.removeEventListener("abort", onAbort);
    session.dispose();
  };

  let result: StepSessionResult;
  try {
    result = await runPrompt(task);
  } catch (error) {
    dispose();
    throw error;
  }

  return {
    result,
    // Rejected handoffs come back to the same session (same model, full step
    // context) so the reviser knows everything it already did.
    revise: (feedback) => runPrompt(feedback),
    dispose,
  };
}
