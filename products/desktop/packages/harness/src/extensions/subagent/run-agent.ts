/**
 * Turns an `AgentConfig` + task into one concrete child pi process run:
 * resolves effective settings/overrides, auth, and policy (`settings.ts`,
 * `auth.ts`, `policy.ts`), builds the child's argv and generated support
 * files (auth bridge, system prompt), spawns it (`process/child-process.ts`),
 * and parses its `--mode json` stdout into a `SingleRunResult`.
 *
 * This is the only module that knows how to go from "an agent and a task" to
 * "a running child process" — `process/pool.ts` and `chain.ts` only ever call
 * `runAgent`, never touch `process/child-process.ts` or `auth.ts` directly.
 */
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { Message } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { withFileMutationQueue } from "@earendil-works/pi-coding-agent";
import type { AgentConfig } from "./agents";
import { resolveModelAuthWithFallback, writeAuthBridgeExtension } from "./auth";
import { composeTaskWithContext, resolveContext } from "./context";
import {
  getResultOutput,
  renderTranscriptMarkdown,
  truncateForModel,
} from "./format";
import { createRunId, endRun, startRun, writeTranscript } from "./lifecycle";
import { applyModelScope, SubagentPolicyError } from "./policy";
import {
  type ChildProcessHandle,
  spawnChildProcess,
} from "./process/child-process";
import { piCliInvocation } from "./process/pi-subprocess";
import { applyAgentOverrides, loadSubagentSettings } from "./settings";
import { removeAgentRun, upsertAgentRun } from "./status-registry";

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
  exitCode: number;
  messages: Message[];
  stderr: string;
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
  return (
    result.exitCode !== 0 ||
    result.stopReason === "error" ||
    result.stopReason === "aborted"
  );
}

/** Sibling extension entry points resolved by relative path — not through
 * the registry — so this module has no dependency on the harness extension
 * registry or on any specific provider extension. */
function siblingExtensionFile(name: string): string {
  return fileURLToPath(new URL(`../${name}/index.js`, import.meta.url));
}

async function writePromptToTempFile(
  agentName: string,
  prompt: string,
): Promise<{ dir: string; filePath: string }> {
  const tmpDir = await fs.promises.mkdtemp(
    path.join(os.tmpdir(), "posthog-subagent-prompt-"),
  );
  const safeName = agentName.replace(/[^\w.-]+/g, "_");
  const filePath = path.join(tmpDir, `prompt-${safeName}.md`);
  await withFileMutationQueue(filePath, async () => {
    await fs.promises.writeFile(filePath, prompt, {
      encoding: "utf-8",
      mode: 0o600,
    });
  });
  return { dir: tmpDir, filePath };
}

async function rmTempDir(dir: string | null): Promise<void> {
  if (!dir) return;
  await fs.promises.rm(dir, { recursive: true, force: true }).catch(() => {});
}

export type OnRunUpdate = (partial: SingleRunResult) => void;

export interface RunAgentOptions {
  ctx: ExtensionContext;
  agent: AgentConfig;
  task: string;
  cwd?: string;
  step?: number;
  signal?: AbortSignal;
  /** Explicit context to forward to the child, on top of `task`. Falls back to a small auto-digest of recent parent turns when unset. */
  context?: string;
  onUpdate?: OnRunUpdate;
  /** Publish this run in the standalone subagent footer. Default: true. */
  publishStatus?: boolean;
  /** Also load `web-access` (web_search/web_fetch) in the child. Default: inferred from `agent.tools`. */
  includeWebAccess?: boolean;
}

function parseStdoutLine(
  result: SingleRunResult,
  line: string,
  emitUpdate: () => void,
): void {
  if (!line.trim()) return;
  let event: { type?: string; message?: Message };
  try {
    event = JSON.parse(line);
  } catch {
    return;
  }

  if (
    (event.type !== "message_end" && event.type !== "tool_result_end") ||
    !event.message
  )
    return;

  const msg = event.message;
  result.messages.push(msg);

  if (msg.role === "assistant") {
    result.usage.turns++;
    const usage = msg.usage;
    if (usage) {
      result.usage.input += usage.input || 0;
      result.usage.output += usage.output || 0;
      result.usage.cacheRead += usage.cacheRead || 0;
      result.usage.cacheWrite += usage.cacheWrite || 0;
      result.usage.cost += usage.cost?.total || 0;
      result.usage.contextTokens = usage.totalTokens || 0;
    }
    if (msg.stopReason) result.stopReason = msg.stopReason;
    if (msg.errorMessage) result.errorMessage = msg.errorMessage;
  }
  emitUpdate();
}

/**
 * Runs one agent against one task in an isolated child pi process and
 * resolves once the child exits. Callers await this directly.
 */
export async function runAgent(
  options: RunAgentOptions,
): Promise<SingleRunResult> {
  const { ctx, agent, task, cwd, step, signal, onUpdate } = options;
  const publishStandaloneStatus = options.publishStatus ?? true;
  const runId = createRunId();
  // Every `runAgent` call — whether it's a plain single run, one task in a
  // parallel fan-out, or one step in a chain — gets its own lifecycle status
  // + transcript for later inspection.
  const lifecycleStatus = startRun({
    runId,
    mode: "single",
    agents: [agent.name],
  });

  // `-1` is the sentinel `render.ts` uses to mean "still running" — every
  // completion path below (success, catch blocks, `handle.exited`) overwrites
  // this before returning, so a caller streaming `onUpdate` sees `-1` for the
  // whole in-flight duration and a real exit code once the run finishes.
  const result: SingleRunResult = {
    runId,
    agent: agent.name,
    task,
    exitCode: -1,
    messages: [],
    stderr: "",
    usage: emptyUsage(),
    step,
    startedAt: lifecycleStatus.startedAt,
  };

  let composedPrompt: string | undefined;
  const publishStatus = () => {
    if (!publishStandaloneStatus) return;
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
  publishStatus();

  let authBridgeDir: string | null = null;
  let tmpPromptDir: string | null = null;
  let handle: ChildProcessHandle | undefined;
  const onAbort = () => handle?.kill();

  try {
    const settings = loadSubagentSettings(ctx.cwd, ctx.isProjectTrusted());
    const effectiveAgent = applyAgentOverrides(agent, settings);

    const modelAuth = await resolveModelAuthWithFallback(
      ctx,
      effectiveAgent.name,
      effectiveAgent.model,
      effectiveAgent.fallbackModels,
    ).catch((error: unknown) => {
      result.exitCode = 1;
      result.stopReason = "error";
      result.errorMessage =
        error instanceof Error ? error.message : String(error);
      return undefined;
    });
    if (!modelAuth) return result;
    result.model = `${modelAuth.model.provider}/${modelAuth.model.id}`;
    publishStatus();

    try {
      result.warning = applyModelScope(result.model, settings.modelScope);
    } catch (error) {
      result.exitCode = 1;
      result.stopReason = "error";
      result.errorMessage =
        error instanceof SubagentPolicyError ? error.message : String(error);
      return result;
    }

    const authBridge = await writeAuthBridgeExtension(modelAuth);
    authBridgeDir = authBridge.dir;

    const args: string[] = ["--mode", "json", "-p", "--no-session"];
    args.push("-e", authBridge.filePath);

    const wantsWebAccess =
      options.includeWebAccess ??
      effectiveAgent.tools?.some(
        (t) => t === "web_search" || t === "web_fetch",
      ) ??
      false;
    if (wantsWebAccess) args.push("-e", siblingExtensionFile("web-access"));

    args.push("--model", result.model);
    if (effectiveAgent.tools && effectiveAgent.tools.length > 0)
      args.push("--tools", effectiveAgent.tools.join(","));
    if (effectiveAgent.thinking)
      args.push("--thinking", effectiveAgent.thinking);

    // Agent definitions (bundled `bundled-agents/*.md` or project-local
    // `.pi/agents/*.md`) with a non-empty body are standalone personas, not
    // an addendum to pi's default coding-agent system prompt — `--system-prompt`
    // replaces it outright rather than appending to it.
    //
    // An agent with an *empty* body (e.g. `General.md`) deliberately skips
    // this: with no `--system-prompt` flag, the child computes pi's own
    // live default system prompt itself (tools list, guidelines merged from
    // every loaded extension's `promptGuidelines`, project context, skills)
    // — the same one a normal interactive session gets, always in sync with
    // pi's own template. That's the right choice for a persona that's meant
    // to be a fully general, unconstrained agent rather than a narrower
    // custom-prompted specialist like `Explore`/`Plan`.
    if (effectiveAgent.systemPrompt.trim()) {
      const tmp = await writePromptToTempFile(
        effectiveAgent.name,
        effectiveAgent.systemPrompt,
      );
      tmpPromptDir = tmp.dir;
      args.push("--system-prompt", tmp.filePath);
    }

    const forwardedContext = resolveContext(ctx, options.context);
    composedPrompt = composeTaskWithContext(task, forwardedContext);
    args.push(composedPrompt);
    publishStatus();

    const invocation = piCliInvocation(args);
    const emitUpdate = () => {
      onUpdate?.(result);
      publishStatus();
    };

    handle = spawnChildProcess({
      command: invocation.command,
      args: invocation.args,
      cwd: cwd ?? ctx.cwd,
      env: invocation.env,
      onStdoutLine: (line) => parseStdoutLine(result, line, emitUpdate),
      onStderrChunk: (chunk) => {
        result.stderr += chunk;
      },
    });

    if (signal) {
      if (signal.aborted) onAbort();
      else signal.addEventListener("abort", onAbort, { once: true });
    }

    result.exitCode = await handle.exited;
    if (signal?.aborted) {
      result.stopReason = "aborted";
      result.errorMessage = "Subagent was aborted";
    }
    return result;
  } finally {
    result.endedAt = Date.now();
    signal?.removeEventListener("abort", onAbort);
    if (publishStandaloneStatus) removeAgentRun(runId);
    try {
      writeTranscript(runId, renderTranscriptMarkdown(result));
      endRun(
        lifecycleStatus,
        result.stopReason === "aborted"
          ? "aborted"
          : isFailedResult(result)
            ? "failed"
            : "completed",
        result.errorMessage,
        {
          model: result.model,
          totalTokens:
            result.usage.contextTokens ||
            result.usage.input + result.usage.output,
          totalCost: result.usage.cost,
          resultSummary: truncateForModel(getResultOutput(result), 2000),
        },
      );
    } catch {
      /* lifecycle/transcript persistence is best-effort; never fail the run over it */
    }
    await rmTempDir(authBridgeDir);
    await rmTempDir(tmpPromptDir);
  }
}
