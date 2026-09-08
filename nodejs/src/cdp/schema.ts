import { z } from 'zod'

export const CdpInternalEventSchema = z.object({
    team_id: z.number(),
    event: z.object({
        uuid: z.string(),
        event: z.string(),
        // In this context distinct_id should be whatever we want to use if doing follow up things (like tracking a standard event)
        distinct_id: z.string(),
        properties: z.record(z.string(), z.any()),
        timestamp: z.string(),
        url: z.string().optional().nullable(),
    }),
    // Person may be a event-style person or an org member
    person: z
        .object({
            id: z.string(),
            properties: z.record(z.string(), z.any()),
            name: z.string().optional().nullable(),
            url: z.string().optional().nullable(),
        })
        .optional()
        .nullable(),
})

// Infer the TypeScript type
export type CdpInternalEvent = z.infer<typeof CdpInternalEventSchema>

export const CdpDataWarehouseEventSchema = z.object({
    team_id: z.number(),
    // Dot-notated table name the row was synced into, or a materialized view's own name. Optional
    // for backwards compatibility with messages produced before the producer started including it.
    table_name: z.string().optional(),
    // Which kind of warehouse table the row came from. Absent means a source-synced table, which is
    // all the producer emitted before materialized views could trigger.
    table_type: z.enum(['source', 'view']).optional(),
    // Deterministic id, unique per row (see CDPProducer._build_event_id)
    event_id: z.string(),
    properties: z.record(z.string(), z.any()),
})

// Infer the TypeScript type
export type CdpDataWarehouseEvent = z.infer<typeof CdpDataWarehouseEventSchema>
