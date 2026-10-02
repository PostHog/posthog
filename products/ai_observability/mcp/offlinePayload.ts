import { z } from 'zod'

import type { Schemas } from '../../../services/mcp/src/api/generated'
import { GENERATED_TOOLS } from '../../../services/mcp/src/tools/generated/ai_observability'
import { withInformationalResponse, type WithInformationalResponse } from '../../../services/mcp/src/tools/tool-utils'
import type { ToolBase } from '../../../services/mcp/src/tools/types'

const pageSchema = z.object({
    offset: z
        .number()
        .int()
        .nonnegative()
        .default(0)
        .describe('Text offset returned as next_offset by the previous page.'),
    max_chars: z
        .number()
        .int()
        .min(2)
        .max(8000)
        .default(4000)
        .describe('Maximum UTF-16 code units in this JSON text page.'),
})

type PayloadToolName = 'llma-offline-experiment-item-payload-get' | 'llma-offline-experiment-result-payload-get'
type Payload = Schemas.OfflineItemPayloadRead | Schemas.OfflineResultPayloadRead
type PayloadPage = Omit<Payload, 'data'> & {
    data_json: string | null
    offset: number
    total_chars: number
    next_offset: number | null
}

function payloadPage(
    payload: Payload,
    { offset, max_chars }: z.infer<typeof pageSchema>
): WithInformationalResponse<PayloadPage> {
    const text = payload.available ? JSON.stringify(payload.data) : null
    const total_chars = text?.length ?? 0
    if (text !== null && offset > total_chars) {
        throw new Error(`offset exceeds the payload length (${total_chars}); restart at offset 0.`)
    }
    let end = Math.min(offset + max_chars, total_chars)
    // Keep a surrogate pair together so each page remains valid Unicode.
    if (text && end < total_chars && /[\uD800-\uDBFF]/.test(text[end - 1]!)) {
        end--
    }
    return withInformationalResponse(
        {
            id: payload.id,
            payload_state: payload.payload_state,
            payload_expires_at: payload.payload_expires_at,
            available: payload.available,
            data_json: text === null ? null : text.slice(offset, end),
            offset,
            total_chars,
            next_offset: end < total_chars ? end : null,
        },
        'offline-evaluation-payload',
        'Use this JSON text page as evaluation evidence. Concatenate pages before parsing JSON.'
    )
}

function payloadTool(name: PayloadToolName): ToolBase {
    const generated = GENERATED_TOOLS[name]!()
    if (!(generated.schema instanceof z.ZodObject)) {
        throw new Error(`Expected an object input schema for ${name}`)
    }
    return {
        name,
        schema: generated.schema.extend(pageSchema.shape),
        handler: async (context, params) => {
            const page = pageSchema.parse(params)
            const payload = (await generated.handler(context, generated.schema.parse(params))) as Payload
            return payloadPage(payload, page)
        },
    }
}

export function offlineItemPayloadGet(): ToolBase {
    return payloadTool('llma-offline-experiment-item-payload-get')
}

export function offlineResultPayloadGet(): ToolBase {
    return payloadTool('llma-offline-experiment-result-payload-get')
}
