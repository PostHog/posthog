import { realpathSync } from "node:fs";
import { isAbsolute, relative, sep } from "node:path";
import type { Message } from "@earendil-works/pi-ai";
import {
  type AgentSession,
  createAgentSession,
  DefaultResourceLoader,
  type ExtensionContext,
  getAgentDir,
  ProjectTrustStore,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";
import {
  type AgentRunState,
  createPiToolCallRecord,
  type PiSubagentToolCall,
} from "@posthog/shared";
import { createWebAccessExtension } from "../web-access/extension";
import type { AgentConfig } from "./agents";
import {
  createSubagentModelRuntime,
  resolveModelAuthWithFallback,
} from "./auth";
import { composeTaskWithContext, resolveContext } from "./context";
import {
  getResultOutput,
  renderTranscriptMarkdown,
  truncateForModel,
} from "./format";
import {
  createRunId,
  endRun,
  type RunState,
  startRun,
  writeTranscript,
} from "./lifecycle";
import { applyModelScope, SubagentPolicyError } from "./policy";
import { applyAgentOverrides, loadSubagentSettings } from "./settings";
import { removeAgentRun, upsertAgentRun } from "./ui/status-registry";

function inheritsParentProjectTrust(
  ctx: ExtensionContext,
  workingDirectory: string,
): boolean {
  if (!ctx.isProjectTrusted()) {
    return false;
  }

  try {
    const parentDirectory = realpathSync(ctx.cwd);
    const childDirectory = realpathSync(workingDirectory);
    const relativePath = relative(parentDirectory, childDirectory);
    const outsideParent =
      relativePath === ".." ||
      relativePath.startsWith(`..${sep}`) ||
      isAbsolute(relativePath);
    if (outsideParent) {
      return false;
    }

    return new ProjectTrustStore(getAgentDir()).get(childDirectory) !== false;
  } catch {
    return false;
  }
}

export interface UsageStats {
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
  cost: number;
  contextTokens: number;
  turns: number;
}

export interface SingleRunResult {
  runId: string;
  agent: string;
  task: string;
  description?: string;
  toolCalls?: PiSubagentToolCall[];
  state: AgentRunState;
  messages: Message[];
  resultText?: string;
  usage: UsageStats;
  model?: string;
  stopReason?: string;
  errorMessage?: string;
  warning?: string;
  step?: number;
  startedAt: number;
  endedAt?: number;
}

function emptyUsage(): UsageStats {
  return {
    input: 0,
    output: 0,
    cacheRead: 0,
    cacheWrite: 0,
    cost: 0,
    contextTokens: 0,
    turns: 0,
  };
}

export function isFailedResult(result: SingleRunResult): boolean {
  return result.state === "failed" || result.state === "aborted";
}

export type OnRunUpdate = (partial: SingleRunResult) => void;

export interface RunAgentOptions {
  ctx: ExtensionContext;
  agent: AgentConfig;
  task: string;
  description?: string;
  cwd?: string;
  step?: number;
  signal?: AbortSignal;
  context?: string;
  useAutoContext?: boolean;
  onUpdate?: OnRunUpdate;
  publishStatus?: boolean;
  includeWebAccess?: boolean;
}

function finalRunState(result: SingleRunResult): Exclude<RunState, "running"> {
  if (result.stopReason === "aborted") {
    return "aborted";
  }
  if (isFailedResult(result)) {
    return "failed";
  }
  return "completed";
}

function finalizeToolCalls(
  toolCalls: PiSubagentToolCall[],
  state: AgentRunState,
): PiSubagentToolCall[] {
  if (state === "running") {
    return toolCalls;
  }

  const unfinishedStatus = state === "completed" ? "completed" : "failed";
  return toolCalls.map((toolCall) =>
    toolCall.status === "in_progress"
      ? { ...toolCall, status: unfinishedStatus }
      : toolCall,
  );
}

function errorMessage(error: unknown, aborted: boolean): string {
  if (aborted) {
    return "Subagent was aborted";
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function recordMessage(
  result: SingleRunResult,
  toolCallsById: Map<string, PiSubagentToolCall>,
  message: Message,
  emitUpdate: () => void,
): void {
  result.messages.push(message);

  if (message.role === "assistant") {
    for (const block of message.content) {
      if (block.type === "toolCall") {
        const toolCall: PiSubagentToolCall = createPiToolCallRecord(
          { id: block.id, name: block.name, arguments: block.arguments },
          "in_progress",
        );
        result.toolCalls ??= [];
        result.toolCalls.push(toolCall);
        toolCallsById.set(toolCall.id, toolCall);
      }
    }

    result.usage.turns++;
    const usage = message.usage;
    if (usage) {
      result.usage.input += usage.input || 0;
      result.usage.output += usage.output || 0;
      result.usage.cacheRead += usage.cacheRead || 0;
      result.usage.cacheWrite += usage.cacheWrite || 0;
      result.usage.cost += usage.cost?.total || 0;
      result.usage.contextTokens = usage.totalTokens || 0;
    }
    if (message.stopReason) {
      result.stopReason = message.stopReason;
    }
    if (message.errorMessage) {
      result.errorMessage = message.errorMessage;
    }
  } else if (message.role === "toolResult") {
    const toolCall = toolCallsById.get(message.toolCallId);
    if (toolCall) {
      toolCall.status = message.isError ? "failed" : "completed";
    }
  }

  emitUpdate();
}

export async function runAgent(
  options: RunAgentOptions,
): Promise<SingleRunResult> {
  const { ctx, agent, task, cwd, step, signal, onUpdate } = options;
  const publishStandaloneStatus = options.publishStatus ?? true;
  const runId = createRunId();
  const lifecycleStatus = startRun({
    runId,
    mode: "single",
    agents: [agent.name],
  });

  const result: SingleRunResult = {
    runId,
    agent: agent.name,
    task,
    description: options.description,
    state: "running",
    messages: [],
    toolCalls: [],
    usage: emptyUsage(),
    step,
    startedAt: lifecycleStatus.startedAt,
  };

  let composedPrompt: string | undefined;
  const publishStatus = () => {
    if (!publishStandaloneStatus) {
      return;
    }
    upsertAgentRun({
      runId,
      agent: result.agent,
      task: result.task,
      composedPrompt,
      model: result.model,
      startedAt: result.startedAt,
      usage: result.usage,
      messages: result.messages,
      errorMessage: result.errorMessage,
    });
  };

  const toolCallsById = new Map<string, PiSubagentToolCall>();
  const emitUpdate = () => {
    result.toolCalls = finalizeToolCalls(result.toolCalls ?? [], result.state);
    onUpdate?.({
      ...result,
      messages: [...result.messages],
      usage: { ...result.usage },
    });
    publishStatus();
  };
  emitUpdate();

  let childSession: AgentSession | undefined;
  let unsubscribeSession: (() => void) | undefined;
  const onAbort = () => {
    void childSession?.abort();
  };

  try {
    const workingDirectory = cwd ?? ctx.cwd;
    const projectTrusted = inheritsParentProjectTrust(ctx, workingDirectory);
    const settings = loadSubagentSettings(workingDirectory, projectTrusted);
    const effectiveAgent = applyAgentOverrides(agent, settings);

    const modelAuth = await resolveModelAuthWithFallback(
      ctx,
      effectiveAgent.name,
      effectiveAgent.model,
      effectiveAgent.fallbackModels,
    ).catch((error: unknown) => {
      result.state = "failed";
      result.stopReason = "error";
      result.errorMessage =
        error instanceof Error ? error.message : String(error);
      return undefined;
    });
    if (!modelAuth) {
      return result;
    }

    result.model = `${modelAuth.model.provider}/${modelAuth.model.id}`;
    emitUpdate();

    try {
      result.warning = applyModelScope(result.model, settings.modelScope);
    } catch (error) {
      result.state = "failed";
      result.stopReason = "error";
      result.errorMessage =
        error instanceof SubagentPolicyError ? error.message : String(error);
      return result;
    }

    const { model, modelRuntime } = await createSubagentModelRuntime(modelAuth);
    const settingsManager = SettingsManager.create(
      workingDirectory,
      getAgentDir(),
      { projectTrusted },
    );
    const wantsWebAccess =
      options.includeWebAccess ??
      effectiveAgent.tools?.some(
        (tool) => tool === "web_search" || tool === "web_fetch",
      ) ??
      false;
    const extensionFactories = wantsWebAccess
      ? [{ name: "web-access", factory: createWebAccessExtension() }]
      : [];
    const systemPrompt = effectiveAgent.systemPrompt.trim() || undefined;
    const resourceLoader = new DefaultResourceLoader({
      cwd: workingDirectory,
      agentDir: getAgentDir(),
      settingsManager,
      noExtensions: true,
      noContextFiles: !projectTrusted,
      extensionFactories,
      systemPrompt,
    });
    await resourceLoader.reload();

    const sessionResult = await createAgentSession({
      cwd: workingDirectory,
      agentDir: getAgentDir(),
      model,
      modelRuntime,
      thinkingLevel: effectiveAgent.thinking,
      tools: effectiveAgent.tools,
      resourceLoader,
      sessionManager: SessionManager.inMemory(workingDirectory),
      settingsManager,
    });
    childSession = sessionResult.session;
    unsubscribeSession = childSession.subscribe((event) => {
      if (
        event.type === "message_end" &&
        (event.message.role === "assistant" ||
          event.message.role === "toolResult")
      ) {
        recordMessage(result, toolCallsById, event.message, emitUpdate);
      }
    });

    const forwardedContext =
      options.useAutoContext === false
        ? ""
        : resolveContext(ctx, options.context);
    composedPrompt = composeTaskWithContext(task, forwardedContext);
    emitUpdate();

    if (signal?.aborted) {
      result.state = "aborted";
      result.stopReason = "aborted";
      result.errorMessage = "Subagent was aborted";
      return result;
    }
    signal?.addEventListener("abort", onAbort, { once: true });

    await childSession.prompt(composedPrompt);
    if (signal?.aborted) {
      result.state = "aborted";
      result.stopReason = "aborted";
      result.errorMessage = "Subagent was aborted";
    } else if (result.stopReason === "aborted") {
      result.state = "aborted";
    } else if (result.stopReason === "error") {
      result.state = "failed";
    } else {
      result.state = "completed";
    }
    emitUpdate();
    return result;
  } catch (error) {
    const aborted = signal?.aborted ?? false;
    result.state = aborted ? "aborted" : "failed";
    result.stopReason = aborted ? "aborted" : "error";
    result.errorMessage = errorMessage(error, aborted);
    return result;
  } finally {
    result.endedAt = Date.now();
    try {
      emitUpdate();
    } catch {
      // Status updates must not replace the run result.
    }
    signal?.removeEventListener("abort", onAbort);
    unsubscribeSession?.();
    childSession?.dispose();
    if (publishStandaloneStatus) {
      removeAgentRun(runId);
    }
    try {
      writeTranscript(runId, renderTranscriptMarkdown(result));
      endRun(lifecycleStatus, finalRunState(result), result.errorMessage, {
        model: result.model,
        totalTokens:
          result.usage.contextTokens ||
          result.usage.input + result.usage.output,
        totalCost: result.usage.cost,
        resultSummary: truncateForModel(getResultOutput(result), 2000),
      });
    } catch {
      /* lifecycle/transcript persistence is best-effort; never fail the run over it */
    }
  }
}
