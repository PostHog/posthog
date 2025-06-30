import { z } from 'zod'

export const CyclotronInputSchema = z.object({
    value: z.any(),
    templating: z.enum(['hog', 'liquid']).optional(),
    secret: z.boolean().optional(),
    bytecode: z.any().optional(),
    order: z.number().optional(),
})

export type CyclotronInputType = z.infer<typeof CyclotronInputSchema>
