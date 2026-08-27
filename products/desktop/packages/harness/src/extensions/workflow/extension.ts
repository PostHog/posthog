/**
 * The `workflow` tool: Claude-Code-style dynamic workflows for pi. The model
 * writes one JavaScript orchestration script; `runtime.ts` executes it in a
 * `vm` sandbox; every `agent()` call in the script becomes one isolated child
 * pi process via the subagent package's `runAgent` — so workflows inherit all
 * of its machinery for free (PostHog gateway auth bridging, model fallback,
 * policy, lifecycle status, persisted transcripts, abort-kills-child).
 *
 * Only bundled agents (Explore, Plan, General) are runnable from scripts —
 * same fixed, audited personas the `subagent` tool uses, discovered the same
 * way (`discoverAgents(cwd, "bundled")`). Explore/Plan are read-only;
 * General has the same read-write capability as the orchestrating session
 * and is the one to reach for when a workflow needs to actually make edits,
 * not just investigate them.
 */
import { fileURLToPath } from "node:url";
import type {
  ExtensionAPI,
  ExtensionFactory,
} from "@earendil-works/pi-coding-agent";
import { defineTool } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import type { PosthogProviderOptions } from "../posthog-provider/provider";
import type { AgentConfig } from "../subagent/agents";
import { discoverAgents } from "../subagent/discovery";
import { getResultOutput, truncateForModel } from "../subagent/format";
import {
  isFailedResult,
  runAgent,
  type SingleRunResult,
} from "../subagent/run-agent";
import {
  previewOf,
  renderWorkflowCall,
  renderWorkflowResult,
  type WorkflowSnapshot,
} from "./render";
import {
  extractWorkflowName,
  extractWorkflowPhaseMetadata,
  extractWorkflowPhases,
  normalizeWorkflowScript,
  runWorkflowScript,
} from "./runtime";
import { removeWorkflow, upsertWorkflow } from "./status-registry";

export type WorkflowOptions = PosthogProviderOptions;

const MAX_AGENTS = 256;
const CONCURRENCY = 8;

/**
 * Tier keywords a script may pass as `agent(prompt, { model })`, resolved to
 * concrete *bare* model ids (no provider prefix) so resolution stays
 * host-agnostic — `resolveModelAuth` already resolves a bare id against
 * whatever provider the parent session is currently using, the same way a
 * bundled persona's own `model:` frontmatter (e.g. `Explore.md`) does. A
 * script expresses intent ("this needs my best model"), never a concrete id
 * it would otherwise have to guess and that could silently be wrong — the
 * gateway's model list is fetched dynamically and changes over time.
 *
 * Deliberately just two extra tiers, not the arbitrary N a user-configurable
 * tiers file would need: `strong`/`medium`/`cheap` are fixed, known-good
 * anchors, not a new settings surface.
 */
const MODEL_TIERS: Record<string, string> = {
  strong: "claude-opus-4-8",
  medium: "claude-sonnet-5",
  cheap: "claude-haiku-4-5",
};

/** A tier keyword resolves to its mapped id; anything else (a bare id or an explicit `provider/id`) passes through unchanged as an escape hatch. */
function resolveModelRequest(model: string): string {
  return MODEL_TIERS[model] ?? model;
}

const WorkflowParams = Type.Object({
  script: Type.String({
    description: [
      "Raw JavaScript workflow script (no Markdown fences).",
      "Available globals: agent(prompt, {label, agent?, schema?, cwd?, model?, objective?, inputs?, produces?}), parallel(arrayOfFunctions), pipeline(items, ...stages), phase(title, {goal?, inputs?, produces?}), publish(name, value), log(message), parseJson(text), args, cwd.",
      "agent() returns the subagent's final text — or the parsed JSON object when schema is set — or null on failure. The script's return value is the workflow result.",
    ].join(" "),
  }),
  args: Type.Optional(
    Type.Any({
      description:
        "Optional JSON value exposed to the workflow script as global `args`.",
    }),
  ),
});

type WorkflowToolResult = {
  content: Array<{ type: "text"; text: string }>;
  details: WorkflowSnapshot;
  isError?: boolean;
};

export function createWorkflowExtension(
  options: WorkflowOptions = {},
): ExtensionFactory {
  return (pi: ExtensionAPI) => {
    void options;

    pi.on("resources_discover", () => ({
      skillPaths: [fileURLToPath(new URL("./skills", import.meta.url))],
    }));

    pi.registerTool(
      defineTool({
        name: "workflow",
        label: "Workflow",
        description: [
          "Execute a JavaScript workflow script that orchestrates multiple subagents with agent(), parallel(), and pipeline().",
          "The script holds the loop and intermediate results; subagents (Explore, Plan, General) do the work; only the returned value comes back to your context.",
          "Use for decomposable fan-out work: codebase audits, multi-perspective review, wide research, fan-out/fan-in synthesis, or applying the same kind of edit across many independent files.",
        ].join(" "),
        promptSnippet:
          "Run a JavaScript workflow that fans work out across subagents (agent(), parallel(), pipeline(), phase()) and returns one synthesized result",
        promptGuidelines: [
          "Use workflow when a task decomposes into several independent investigations or changes (audit many files, research many topics, review from multiple perspectives, edit many independent files). Do not use it for a single quick read or edit, or when the subagent tool alone is enough.",
          "For workflow, pass one raw JavaScript string in `script` — no Markdown fences, no TypeScript, no import/export statements or require() (a leading `export const meta = {name, description}` is tolerated).",
          "For workflow, available globals: agent(prompt, {label, agent?, schema?, cwd?, model?, objective?, inputs?, produces?}), parallel(arrayOfFunctions), pipeline(items, ...stages), phase(title, {goal?, inputs?, produces?}), log(message), parseJson(text), args, cwd. Anything else (require, fs, fetch, setTimeout) is unavailable.",
          "For workflow, agent() runs one isolated subagent and resolves to its final text, or null if it failed — check for nulls before synthesizing. Valid agent names: 'Explore' (default; fast read-only recon), 'Plan' (read-only implementation planning), 'General' (read-write — makes real edits).",
          "For workflow, only General edits files; Explore and Plan are read-only. Use General for the actual changes an Explore/Plan investigation identified, or any fan-out that needs real edits, not just findings.",
          "For workflow, agent()'s optional model lets a call use a different model than its persona's default: 'strong' (best available model), 'medium', or 'cheap' (fast/cheap) — use these tier keywords, not a guessed exact model id, since the available model list changes over time. Omit model to use the persona's own default.",
          "For workflow, when an agent's output feeds later stages, pass a plain JSON Schema via {schema: {type: 'object', required: [...], properties: {...}}} — agent() then returns the parsed, shape-checked object instead of text. Use JSON Schema syntax, not TypeScript.",
          "For workflow, parallel() takes functions, not promises: `await parallel(items.map(item => () => agent(...)))`. Results come back in input order. At most 8 agents run concurrently and 256 per workflow.",
          "For workflow, pipeline(items, ...stages) fans items out through sequential stages (map → verify → summarize); different items run concurrently, each item's stages run in order, and each stage receives (previousValue, originalItem, index).",
          "For reliable workflows, use a literal `export const meta = {name, goal?, inputs?: string[], phases: [{title, goal?, inputs: string[], produces: string[]}], synthesis: {phase, inputs: string[], produces: string[]}}` declared plan. That strict mode preflights dependency order, requires phases in order, named outputs exactly once, and makes agent input arrays real artifact handoffs. Give each agent a unique label/objective and inputs/produces; the final synthesis agent must publish the declared final artifact. Legacy scripts without a literal meta.phases retain record-style inputs. Never invent token budgets.",
          "For workflow, subagents share no context with you or each other: put all needed file paths, constraints, and prior findings into each prompt.",
          "For workflow, end with a synthesis step (often one final agent() over the collected findings) and return a compact JSON-serializable value — that value is all that comes back to you.",
        ],
        parameters: WorkflowParams,
        renderCall: renderWorkflowCall,
        renderResult: renderWorkflowResult,
        async execute(
          toolCallId,
          params,
          signal,
          _onUpdate,
          ctx,
        ): Promise<WorkflowToolResult> {
          const script = normalizeWorkflowScript(params.script);
          const discovery = discoverAgents(ctx.cwd, "bundled");
          const agents = new Map<string, AgentConfig>(
            discovery.agents.map((a) => [a.name, a]),
          );
          const agentNames = [...agents.keys()].sort((a, b) =>
            // Explore first: it's the documented default for `agent()`.
            a === "Explore" ? -1 : b === "Explore" ? 1 : a.localeCompare(b),
          );

          const snapshot: WorkflowSnapshot = {
            name: extractWorkflowName(script),
            phases: extractWorkflowPhases(script),
            phaseMetadata: Object.fromEntries(
              extractWorkflowPhaseMetadata(script).flatMap((phase) =>
                phase.metadata ? [[phase.title, phase.metadata]] : [],
              ),
            ),
            agents: [],
            logs: [],
            done: false,
            tokensSpent: 0,
          };
          const agentResults = new Map<number, SingleRunResult>();
          const agentTasks = new Map<number, string>();
          const artifacts: Array<{
            name: string;
            phase: string;
            producer: string;
          }> = [];
          const startedAt = Date.now();
          const publish = () => {
            upsertWorkflow({
              workflowId: toolCallId,
              name: snapshot.name,
              startedAt,
              phases: [...snapshot.phases],
              phaseMetadata: { ...snapshot.phaseMetadata },
              currentPhase: snapshot.currentPhase,
              logs: [...snapshot.logs],
              tokensSpent: snapshot.tokensSpent ?? 0,
              artifacts: [...artifacts],
              agents: snapshot.agents.map((agent) => {
                const result = agentResults.get(agent.id);
                return {
                  ...agent,
                  task: agentTasks.get(agent.id) ?? result?.task ?? "",
                  model: result?.model,
                  usage: result?.usage,
                  messages: result?.messages,
                  errorMessage: result?.errorMessage,
                };
              }),
            });
          };
          // Runtime display belongs to the footer/overlay, not streamed into
          // the tool result. The completed result below stays unchanged.
          publish();

          try {
            const outcome = await runWorkflowScript(
              script,
              {
                agentNames,
                args: params.args,
                cwd: ctx.cwd,
                signal,
                concurrency: CONCURRENCY,
                maxAgents: MAX_AGENTS,
              },
              {
                async runAgentTask(request, taskSignal) {
                  const baseConfig = agents.get(request.agent) as AgentConfig;
                  const config = request.model
                    ? {
                        ...baseConfig,
                        model: resolveModelRequest(request.model),
                      }
                    : baseConfig;
                  const result = await runAgent({
                    ctx,
                    agent: config,
                    task: request.prompt,
                    cwd: request.cwd,
                    signal: taskSignal,
                    publishStatus: false,
                    onUpdate: (partial) => {
                      agentResults.set(request.id, partial);
                      publish();
                    },
                  });
                  agentResults.set(request.id, result);
                  publish();
                  if (isFailedResult(result))
                    throw new Error(getResultOutput(result));
                  const output = getResultOutput(result);
                  return {
                    output,
                    modelOutput: truncateForModel(output),
                    tokens: result.usage.input + result.usage.output,
                  };
                },
                onPhase(title, metadata) {
                  snapshot.currentPhase = title;
                  if (!snapshot.phases.includes(title))
                    snapshot.phases.push(title);
                  if (metadata) {
                    snapshot.phaseMetadata ??= {};
                    snapshot.phaseMetadata[title] = metadata;
                  }
                  publish();
                },
                onArtifact(artifact) {
                  artifacts.push(artifact);
                  publish();
                },
                onLog(message) {
                  snapshot.logs.push(message);
                  publish();
                },
                onAgentStart(event) {
                  agentTasks.set(event.id, event.task);
                  snapshot.agents.push({
                    id: event.id,
                    label: event.label,
                    agent: event.agent,
                    phase: event.phase,
                    objective: event.objective,
                    inputs: event.inputs,
                    produces: event.produces,
                    schema: event.schema,
                    status: "running",
                  });
                  publish();
                },
                onAgentEnd(event) {
                  const entry = snapshot.agents.find((a) => a.id === event.id);
                  if (entry) {
                    entry.status = event.ok ? "done" : "error";
                    entry.resultPreview = previewOf(event.result);
                  }
                  publish();
                },
              },
            );

            snapshot.tokensSpent = outcome.tokensSpent;

            if (outcome.agentCount === 0) {
              return workflowError(
                snapshot,
                "Workflow ran no subagents. Scripts must call agent() at least once — do the work directly if there is nothing to fan out.",
              );
            }

            snapshot.done = true;
            snapshot.result = outcome.result;
            const resultText =
              typeof outcome.result === "string"
                ? outcome.result
                : JSON.stringify(outcome.result, null, 2);
            return {
              content: [
                {
                  type: "text",
                  text: truncateForModel(
                    `Workflow completed with ${outcome.agentCount} agent(s).\n\nResult:\n${resultText}`,
                  ),
                },
              ],
              details: {
                ...snapshot,
                phases: [...snapshot.phases],
                logs: [...snapshot.logs],
                agents: snapshot.agents.map((agent) => ({ ...agent })),
              },
            };
          } catch (error) {
            snapshot.done = true;
            if (signal?.aborted) throw new Error("Workflow was aborted");
            return workflowError(
              snapshot,
              `Workflow failed: ${error instanceof Error ? error.message : String(error)}`,
            );
          } finally {
            removeWorkflow(toolCallId);
          }
        },
      }),
    );
  };
}

function workflowError(
  snapshot: WorkflowSnapshot,
  text: string,
): WorkflowToolResult {
  return {
    content: [{ type: "text", text }],
    details: { ...snapshot, done: true },
    isError: true,
  };
}

export default function workflow(pi: ExtensionAPI): void | Promise<void> {
  return createWorkflowExtension()(pi);
}
