import {
  type AgentSession,
  createAgentSession,
  DefaultResourceLoader,
  type ExtensionContext,
  getAgentDir,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { AGENT_FLOW_HANDOFF_TOOL } from "@posthog/shared";
import type { AgentConfig } from "../subagent/agents";
import { createHandoffTool, type HandoffSubmission } from "./handoff";

const MAX_STEP_TURNS = 80;
const GRACE_TURNS = 5;
const TOOL_OUTPUT_PREVIEW_CAP = 2_000;

export type StepStreamEvent =
  | {
      kind: "tool_start";
      toolCallId: string;
      toolName: string;
      title?: string;
      path?: string;
      diff?: { path: string; oldText?: string | null; newText: string };
    }
  | {
      kind: "tool_end";
      toolCallId: string;
      toolName: string;
      isError?: boolean;
      outputPreview?: string;
    }
  | { kind: "assistant_text"; text: string };

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
  onSteerAvailable?: (steer: (text: string) => void) => void;
}

export interface StepSessionResult {
  output: string;
  failed: boolean;
  errorMessage?: string;
}

export interface StepSessionHandle {
  result: StepSessionResult;
  revise(feedback: string): Promise<StepSessionResult>;
  /** The document the step submitted in its last turn, if it submitted one. */
  peekHandoff?(): HandoffSubmission | null;
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

const DIFF_SIDE_CAP = 20_000;

function toolInputPath(args: unknown): string | undefined {
  if (!args || typeof args !== "object") return undefined;
  const record = args as Record<string, unknown>;
  const path = record.path ?? record.file_path;
  return typeof path === "string" && path.trim() ? path.trim() : undefined;
}

function toolInputDiff(
  toolName: string,
  args: unknown,
): { path: string; oldText?: string | null; newText: string } | undefined {
  const path = toolInputPath(args);
  if (!path || !args || typeof args !== "object") return undefined;
  const record = args as Record<string, unknown>;
  if (toolName === "edit") {
    const oldText = record.oldText ?? record.old_text;
    const newText = record.newText ?? record.new_text;
    if (typeof newText !== "string") return undefined;
    return {
      path,
      oldText:
        typeof oldText === "string" ? oldText.slice(0, DIFF_SIDE_CAP) : null,
      newText: newText.slice(0, DIFF_SIDE_CAP),
    };
  }
  if (toolName === "write") {
    const content = record.content ?? record.text;
    if (typeof content !== "string") return undefined;
    return { path, oldText: null, newText: content.slice(0, DIFF_SIDE_CAP) };
  }
  return undefined;
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
    noExtensions: true,
    noPromptTemplates: true,
    noThemes: true,
    ...(persona ? { systemPromptOverride: () => persona } : {}),
  });
  await loader.reload();

  const parentModelRuntime = (
    ctx.modelRegistry as unknown as { runtime?: unknown }
  ).runtime;

  let submitted: HandoffSubmission | null = null;
  const handoffTool = createHandoffTool((submission) => {
    submitted = submission;
  });

  const { session } = await createAgentSession({
    cwd: ctx.cwd,
    agentDir,
    model,
    ...(options.thinkingLevel
      ? { thinkingLevel: options.thinkingLevel as never }
      : {}),
    customTools: [handoffTool],
    // An allowlist disables every tool it omits, the custom one included.
    ...(agent.tools && agent.tools.length > 0
      ? { tools: [...agent.tools, AGENT_FLOW_HANDOFF_TOOL] }
      : {}),
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
        path: toolInputPath(event.args),
        diff: toolInputDiff(event.toolName, event.args),
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
    submitted = null;
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
    revise: (feedback) => runPrompt(feedback),
    peekHandoff: () => submitted,
    dispose,
  };
}
