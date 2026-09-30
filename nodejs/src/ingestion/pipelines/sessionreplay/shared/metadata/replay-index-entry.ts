import { z } from 'zod'

export const ReplayIndexEntrySchema = z.object({
    kind: z.enum(['full_snapshot', 'json_ld', 'page']),
    windowId: z.string(),
    eventTimestamp: z.number().finite().positive(),
    eventIndex: z.number().int().nonnegative(),
    fullSnapshotTimestamp: z.number().finite().positive().optional(),
    rootTypes: z.array(z.string().max(100)).max(64).optional(),
    url: z.string().max(4096).optional(),
})

export type ReplayIndexEntry = z.infer<typeof ReplayIndexEntrySchema>
