import { StringEnum } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { defineTool } from "@earendil-works/pi-coding-agent";
import type { PiSubagentToolDetails } from "@posthog/shared";
import { Type } from "typebox";
import type { AgentConfig } from "../agents";
import {
  type AgentScope,
  discoverAgents,
  gateProjectAgents,
} from "../discovery";
import {
  formatParallelSummary,
  getResultOutput,
  truncateForModel,
} from "../format";
import { isFailedResult, runAgent, type SingleRunResult } from "../run-agent";
import {
  renderSubagentCall,
  renderSubagentResult,
} from "../ui/subagent-render";

const MAX_CONCURRENT_TASKS = 4;

const CONTEXT_FIELD_DESCRIPTION =
  "Context the agent needs beyond the task itself: file paths already found, decisions already made, constraints. Falls back to a short auto-digest of recent parent turns when omitted, but explicit context is more reliable — prefer passing it.";

const TASK_DESCRIPTION =
  "Brief 2-5-word purpose shown in the tool call, for example: Listing root files. Do not repeat the task.";

const TaskItem = Type.Object({
  agent: Type.String({ description: "Name of the agent to invoke" }),
  task: Type.String({ description: "Task to delegate to the agent" }),
  description: Type.Optional(Type.String({ description: TASK_DESCRIPTION })),
  context: Type.Optional(
    Type.String({ description: CONTEXT_FIELD_DESCRIPTION }),
  ),
  cwd: Type.Optional(
    Type.String({ description: "Working directory for the agent session" }),
  ),
});

const AgentScopeSchema = StringEnum(["bundled", "project", "both"] as const, {
  description:
    'Which agent definitions to use. Default: "bundled" (Explore, Plan). Use "both" to also include project-local .pi/agents/*.md (gated by trust + confirmation).',
  default: "bundled",
});

const SubagentParams = Type.Object({
  agent: Type.Optional(
    Type.String({
      description:
        "Name of the agent for one subagent. Omit when using tasks for parallel work.",
    }),
  ),
  task: Type.Optional(
    Type.String({
      description:
        "Task for one subagent. Omit when using tasks for parallel work.",
    }),
  ),
  description: Type.Optional(Type.String({ description: TASK_DESCRIPTION })),
  context: Type.Optional(
    Type.String({ description: `${CONTEXT_FIELD_DESCRIPTION} (single mode)` }),
  ),
  tasks: Type.Optional(
    Type.Array(TaskItem, {
      description:
        "Tasks to run concurrently. Use this one field for parallel work. Include a brief description in each item.",
    }),
  ),
  agentScope: Type.Optional(AgentScopeSchema),
  confirmProjectAgents: Type.Optional(
    Type.Boolean({
      description:
        "Whether to prompt before running project-local agents. Default: true. Set false only for trusted, already-confirmed automation.",
      default: true,
    }),
  ),
  cwd: Type.Optional(
    Type.String({
      description: "Working directory for the agent session (single mode)",
    }),
  ),
});

interface SubagentToolDetails extends PiSubagentToolDetails {
  results: SingleRunResult[];
}

type SubagentToolResult = {
  content: Array<{ type: "text"; text: string }>;
  details: SubagentToolDetails;
  isError?: boolean;
};

function errorResult(
  text: string,
  mode: SubagentToolDetails["mode"],
): SubagentToolResult {
  return {
    content: [{ type: "text" as const, text }],
    details: { mode, results: [] },
    isError: true,
  };
}

function toToolRunResult(result: SingleRunResult): SingleRunResult {
  const resultText =
    result.state === "running"
      ? undefined
      : truncateForModel(getResultOutput(result));
  return {
    ...result,
    messages: [],
    ...(resultText ? { resultText } : {}),
  };
}

export function registerSubagentTool(pi: ExtensionAPI): void {
  pi.registerTool(
    defineTool({
      name: "subagent",
      label: "Subagent",
      description: [
        "Delegate a task to a focused subagent running in its own isolated Pi session and context window.",
        "For one subagent, pass agent, task, and a brief description. For parallel work, pass tasks with agent, task, and description in each item.",
        "Bundled agents: Explore (focused read-only recon using Sol), Plan (read-only implementation planning), General (read-write implementation — actually makes the requested edits). Only General edits; Explore and Plan never do.",
        'Set agentScope: "both" to also allow project-local .pi/agents/*.md (gated by trust + confirmation).',
      ].join(" "),
      promptSnippet:
        "Delegate a task to a focused subagent (Explore, Plan, General)",
      promptGuidelines: [
        "Use subagent to delegate scoped work (recon, planning, or actual implementation) to an isolated context instead of doing it inline.",
        "Use subagent's parallel mode to run several independent tasks concurrently rather than sequentially.",
        "For a fixed pipeline (e.g. explore then plan then implement), just call subagent multiple times in sequence and pass each result back in as context on the next call — there is no chain mode.",
        "Explore and Plan are read-only and never edit. General has the same read-write capability as you do — use it to delegate actual code changes, especially several independent ones you'd otherwise want to parallelize.",
        "For one subagent, use {agent, task, description}. For parallel work, use {tasks: [{agent, task, description}, ...]}. If top-level agent or task is also present, tasks takes precedence.",
        "Always pass subagent's context field with file paths already found, decisions already made, and constraints — a subagent otherwise only sees its bare task text plus a small auto-generated digest of recent turns.",
        "Subagents cannot themselves call subagent; keep orchestration in the parent session.",
      ],
      parameters: SubagentParams,
      renderCall: renderSubagentCall,
      renderResult: renderSubagentResult,
      async execute(_toolCallId, params, signal, onUpdate, ctx) {
        const agentScope: AgentScope = params.agentScope ?? "bundled";
        const discovery = discoverAgents(ctx.cwd, agentScope);
        const findAgent = (name: string): AgentConfig | undefined =>
          discovery.agents.find((a) => a.name === name);
        const listAvailable = () =>
          discovery.agents.map((a) => `${a.name} (${a.source})`).join(", ") ||
          "none";

        const hasTasks = (params.tasks?.length ?? 0) > 0;
        const hasSingle = Boolean(params.agent && params.task);
        const mode: SubagentToolDetails["mode"] = hasTasks
          ? "parallel"
          : "single";

        if (!hasTasks && !hasSingle) {
          return errorResult(
            `Provide agent and task for one subagent, or a tasks array for parallel subagents. Available agents: ${listAvailable()}`,
            "single",
          );
        }

        if (
          hasTasks &&
          params.tasks &&
          params.tasks.length > MAX_CONCURRENT_TASKS
        ) {
          return errorResult(
            `Too many parallel tasks (${params.tasks.length}). Max is ${MAX_CONCURRENT_TASKS}.`,
            "parallel",
          );
        }
        if (hasTasks && params.tasks) {
          const unknown = params.tasks.filter((t) => !findAgent(t.agent));
          if (unknown.length > 0) {
            return errorResult(
              `Unknown agent(s): ${unknown.map((t) => t.agent).join(", ")}. Available agents: ${listAvailable()}`,
              "parallel",
            );
          }
        }
        const singleAgent = params.agent ? findAgent(params.agent) : undefined;
        if (!hasTasks && hasSingle && !singleAgent) {
          return errorResult(
            `Unknown agent "${params.agent}". Available agents: ${listAvailable()}`,
            "single",
          );
        }

        const requestedNames = new Set<string>();
        for (const task of params.tasks ?? []) {
          requestedNames.add(task.agent);
        }
        if (!hasTasks && params.agent) {
          requestedNames.add(params.agent);
        }
        const requestedAgents = Array.from(requestedNames)
          .map(findAgent)
          .filter((candidate): candidate is AgentConfig => Boolean(candidate));
        const gate = await gateProjectAgents({
          ctx,
          requestedAgents,
          projectAgentsDir: discovery.projectAgentsDir,
          confirmProjectAgents: params.confirmProjectAgents,
        });
        if (!gate.allowed) {
          return errorResult(
            gate.reason ?? "Refused to run project-local agents.",
            mode,
          );
        }

        const publishUpdate = (
          updateMode: SubagentToolDetails["mode"],
          results: SingleRunResult[],
        ) => {
          onUpdate?.({
            content: [],
            details: {
              mode: updateMode,
              results: results.map(toToolRunResult),
            },
          });
        };

        const runDispatch = async (
          dispatchSignal: AbortSignal | undefined,
        ): Promise<SubagentToolResult> => {
          if (hasTasks && params.tasks) {
            const tasks = params.tasks;
            const activeResults = new Map<number, SingleRunResult>();
            const results = await Promise.all(
              tasks.map(async (task, index) => {
                const agent = findAgent(task.agent);
                if (!agent) {
                  throw new Error(`Unknown agent: ${task.agent}`);
                }
                return runAgent({
                  ctx,
                  agent,
                  task: task.task,
                  description: task.description,
                  cwd: task.cwd,
                  context: task.context,
                  signal: dispatchSignal,
                  onUpdate: (partial) => {
                    activeResults.set(index, partial);
                    publishUpdate(
                      "parallel",
                      [...activeResults.entries()]
                        .sort(([left], [right]) => left - right)
                        .map(([, activeResult]) => activeResult),
                    );
                  },
                });
              }),
            );

            return {
              content: [{ type: "text", text: formatParallelSummary(results) }],
              details: {
                mode: "parallel",
                results: results.map(toToolRunResult),
              },
              ...(results.length > 0 && results.every(isFailedResult)
                ? { isError: true }
                : {}),
            };
          }

          if (!singleAgent || !params.task) {
            throw new Error("Single subagent parameters are missing");
          }
          const result = await runAgent({
            ctx,
            agent: singleAgent,
            task: params.task,
            description: params.description,
            cwd: params.cwd,
            context: params.context,
            signal: dispatchSignal,
            onUpdate: (partial) => publishUpdate("single", [partial]),
          });

          if (isFailedResult(result)) {
            return {
              content: [
                {
                  type: "text",
                  text: `Agent ${result.stopReason || "failed"}: ${truncateForModel(getResultOutput(result))}`,
                },
              ],
              details: {
                mode: "single",
                results: [toToolRunResult(result)],
              },
              isError: true,
            };
          }

          return {
            content: [
              {
                type: "text",
                text: truncateForModel(getResultOutput(result)),
              },
            ],
            details: {
              mode: "single",
              results: [toToolRunResult(result)],
            },
          };
        };

        return runDispatch(signal);
      },
    }),
  );
}
