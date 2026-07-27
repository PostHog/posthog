import type { AgentTool, AgentToolResult } from '@earendil-works/pi-agent-core'
import type { TSchema } from '@earendil-works/pi-ai'

import type { ApprovalPolicy } from './approval'
import type { RealToolExecute, ToolResultDetails } from './build-agent-tools'

/** Per-call gate outcome: dispatch for real, or queue for a human decision
 *  under `toolName` (which may differ from the tool's own name — the MCP
 *  proxy's `call_tool` re-keys onto the underlying remote tool). */
export type GateDecision = { gate: false } | { gate: true; toolName: string; policy: ApprovalPolicy }

/** Decide the gate outcome for one call. Most tools ignore the args (a fixed
 *  policy resolved once at session start); the MCP proxy's `call_tool`
 *  inspects `args.tool_name` to re-key the gate per call. */
export type ResolveGate = (toolCallId: string, args: Record<string, unknown>) => GateDecision | Promise<GateDecision>

/** Queues a gated call for a human decision instead of running it. */
export type QueueGated = (
    toolName: string,
    toolCallId: string,
    args: Record<string, unknown>,
    policy: ApprovalPolicy
) => Promise<AgentToolResult<ToolResultDetails>>

/** Set by `gateTool`, checked by `assertToolsGated`. Module-private so
 *  nothing outside this file can forge the brand on a hand-rolled tool. */
const GATED = Symbol('gateTool.branded')

type Gated<T> = T & { [GATED]?: true }

/**
 * Wrap a tool's `execute` so every call is routed through `resolve` first:
 * gated calls queue via `queue` (never touching the real executor); ungated
 * calls run the tool's original `execute` unchanged. Returns a new tool
 * object carrying the brand `assertToolsGated` checks for.
 *
 * This is the ONLY place that is allowed to decide "does this call reach the
 * real executor" — every tool lane (native/custom/client/MCP inline/MCP
 * proxy) must construct its dispatched tool through this function.
 */
export function gateTool(
    tool: AgentTool<TSchema, ToolResultDetails>,
    resolve: ResolveGate,
    queue: QueueGated
): AgentTool<TSchema, ToolResultDetails> {
    const realExecute = tool.execute as RealToolExecute
    const gated: Gated<AgentTool<TSchema, ToolResultDetails>> = {
        ...tool,
        execute: async (toolCallId, args) => {
            const a = (args ?? {}) as Record<string, unknown>
            const decision = await resolve(toolCallId, a)
            return decision.gate ? queue(decision.toolName, toolCallId, a, decision.policy) : realExecute(toolCallId, a)
        },
    }
    gated[GATED] = true
    return gated
}

/**
 * Fail-closed chokepoint: throws (naming the tool) unless every tool carries
 * the brand `gateTool` stamps. Call at the single point the driver hands the
 * tool surface to the model loop — an unbranded tool means some lane built an
 * `AgentTool[]` without routing through `gateTool`.
 */
export function assertToolsGated(tools: ReadonlyArray<AgentTool<TSchema, ToolResultDetails>>): void {
    for (const tool of tools) {
        if (!(tool as Gated<AgentTool<TSchema, ToolResultDetails>>)[GATED]) {
            throw new Error(
                `approval gate bypassed for tool "${tool.name}" — every tool must be wrapped via gateTool() before dispatch`
            )
        }
    }
}
