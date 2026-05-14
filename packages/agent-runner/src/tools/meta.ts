import { z } from 'zod'

import { ToolHandler } from './types'

const CompleteArgsSchema = z.object({
    output: z.unknown(),
})

/**
 * `meta.complete` — explicit completion signal from the SDK. The worker treats this as
 * a terminal tool call: the session is acked and the output is published.
 */
export const completeMetaTool: ToolHandler = {
    id: 'meta.complete',
    async invoke(call) {
        const parsed = CompleteArgsSchema.safeParse(call.args)
        if (!parsed.success) {
            return { ok: false, error: 'meta.complete args invalid: expected { output }' }
        }
        return { ok: true, value: parsed.data.output }
    },
}

const WaitForInputArgsSchema = z.object({
    reason: z.string().min(1).optional(),
})

/**
 * `meta.wait_for_input` — suspend the session until a /send/:id message arrives.
 * The worker recognizes this id and reschedules the job rather than acking it.
 */
export const waitForInputMetaTool: ToolHandler = {
    id: 'meta.wait_for_input',
    async invoke(call) {
        const parsed = WaitForInputArgsSchema.safeParse(call.args)
        if (!parsed.success) {
            return { ok: false, error: 'meta.wait_for_input args invalid' }
        }
        return { ok: true, value: { suspended: true, reason: parsed.data.reason ?? null } }
    },
}

export const META_TOOL_IDS = new Set([completeMetaTool.id, waitForInputMetaTool.id])

export const META_TOOL_HANDLERS: readonly ToolHandler[] = [completeMetaTool, waitForInputMetaTool]
