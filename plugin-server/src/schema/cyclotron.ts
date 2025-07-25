import { z } from 'zod'

export const CyclotronInputSchema = z.object({
    value: z.any(),
    templating: z.enum(['hog', 'liquid']).optional(),
    secret: z.boolean().optional(),
    bytecode: z.any().optional(),
    order: z.number().optional(),
})

export type CyclotronInputType = z.infer<typeof CyclotronInputSchema>

export const CyclotronInvocationQueueParametersFetchSchema = z.object({
    type: z.literal('fetch'),
    url: z.string(),
    method: z.string(),
    body: z.union([z.string(), z.null()]).optional(),
    max_tries: z.number().optional(),
    headers: z.record(z.string(), z.union([z.string(), z.null(), z.undefined()])).optional(),
})

export const CyclotronInvocationQueueParametersEmailSchema = z.object({
    type: z.literal('email'),
    integrationId: z.number(),
    to: z.object({
        email: z.string(),
        name: z.string(),
    }),
    from: z.object({
        email: z.string(),
        name: z.string(),
    }),
    subject: z.string(),
    text: z.string(),
    html: z.string(),
})

export type CyclotronInvocationQueueParametersFetchType = z.infer<typeof CyclotronInvocationQueueParametersFetchSchema>
export type CyclotronInvocationQueueParametersEmailType = z.infer<typeof CyclotronInvocationQueueParametersEmailSchema>

export type CyclotronInvocationQueueParametersType =
    | CyclotronInvocationQueueParametersFetchType
    | CyclotronInvocationQueueParametersEmailType
