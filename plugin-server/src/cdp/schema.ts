import { z } from 'zod'

export const CdpInternalEventSchema = z.object({
    team_id: z.number(),
    event: z.object({
        uuid: z.string(),
        event: z.string(),
        // In this context distinct_id should be whatever we want to use if doing follow up things (like tracking a standard event)
        distinct_id: z.string(),
        properties: z.record(z.any()),
        timestamp: z.string(),
    }),
    // Person may be a event-style person or an org member
    person: z
        .object({
            id: z.string(),
            properties: z.record(z.any()),
            name: z.string(),
        })
        .optional(),
})

// Infer the TypeScript type
export type CdpInternalEvent = z.infer<typeof CdpInternalEventSchema>
