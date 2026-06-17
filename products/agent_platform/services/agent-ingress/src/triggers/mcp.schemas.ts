/**
 * Body / query schemas for the per-agent MCP trigger.
 *
 * MCP traffic is JSON-RPC 2.0 — the envelope is fixed by the protocol. We
 * `safeParse` the envelope at the edge so callers sending malformed JSON-RPC
 * get a clean 400 instead of a confusing `Cannot read property 'method' of
 * undefined`. The inner `params` is left as `unknown` because shape depends
 * on the method (initialize / tools/list / tools/call).
 */

import { z } from 'zod'

export const McpRequestBodySchema = z.object({
    jsonrpc: z.literal('2.0'),
    id: z.union([z.string(), z.number(), z.null()]).optional(),
    method: z.string().min(1),
    params: z.record(z.string(), z.unknown()).optional(),
})

/** Query schema for the streamable-HTTP SSE leg. */
export const McpStreamQuerySchema = z.object({
    session_id: z.string().uuid('session_id must be a UUID'),
})
