import { z } from 'zod'

import { PushNotificationPayloadSchema } from './pushNotification'

export const CyclotronInputSchema = z.object({
    value: z.any(),
    templating: z.enum(['hog', 'liquid']).optional(),
    secret: z.boolean().optional(),
    bytecode: z.any().optional(),
    order: z.number().optional(),
})

export const CyclotronJobInputSchemaTypeSchema = z.object({
    type: z.enum([
        'string',
        'number',
        'boolean',
        'dictionary',
        'choice',
        'json',
        'integration',
        'integration_multi',
        'integration_field',
        'email',
        'native_email',
        'posthog_assignee',
        'posthog_ticket_tags',
        'posthog_business_hours',
        'push_subscription',
        'customer_analytics_account_properties',
    ]),
    key: z.string(),
    label: z.string(),
    choices: z
        .array(
            z.object({
                value: z.string(),
                label: z.string(),
            })
        )
        .optional(),
    required: z.boolean().optional(),
    default: z.any().optional(),
    secret: z.boolean().optional(),
    hidden: z.boolean().optional(),
    templating: z.boolean().optional(),
    description: z.string().optional(),
    integration: z.string().optional(),
    integration_key: z.string().optional(),
    integration_field: z.string().optional(),
    requires_field: z.string().optional(),
    requiredScopes: z.string().optional(),
})

export const CyclotronInputMappingSchema = z.object({
    name: z.string(),
    disabled: z.boolean().optional(),
    inputs_schema: z.array(CyclotronJobInputSchemaTypeSchema).optional(),
    inputs: z.record(z.string(), CyclotronInputSchema).optional().nullable(),
    filters: z.any().optional().nullable(),
})

export type CyclotronJobInputSchemaType = z.infer<typeof CyclotronJobInputSchemaTypeSchema>

export type CyclotronInputType = z.infer<typeof CyclotronInputSchema>

export type CyclotronInputMappingType = z.infer<typeof CyclotronInputMappingSchema>

// When `aws_sigv4` is present on a fetch queue payload, the cyclotron fetch
// executor re-signs the request with AWS Signature V4 immediately before each
// attempt (including retries), overwriting any stale `Authorization` and
// `X-Amz-Date` headers. This is the only path that keeps a retry within AWS's
// 5-minute signature window — never embed a pre-signed Authorization header
// in the queue payload.
//
// Credentials are NOT carried on the queue payload — the `*_input` fields are
// input-key references that the executor resolves against `HogFunction.inputs`
// at fetch time. The cyclotron `cyclotron_jobs.state` blob is plaintext JSON;
// embedding credential strings on the queue payload would defeat the at-rest
// encryption that `EncryptedJSONStringField` provides on
// `posthog_hogfunction.encrypted_inputs`.
export const CyclotronInvocationQueueParametersFetchAwsSigV4Schema = z.object({
    service: z.string(),
    region: z.string(),
    access_key_id_input: z.string(),
    secret_access_key_input: z.string(),
    session_token_input: z.string().optional(),
})

export const CyclotronInvocationQueueParametersFetchSchema = z.object({
    type: z.literal('fetch'),
    url: z.string(),
    method: z.string(),
    body: z.union([z.string(), z.null()]).optional(),
    max_tries: z.number().optional(),
    headers: z.record(z.string(), z.string()).optional(),
    aws_sigv4: CyclotronInvocationQueueParametersFetchAwsSigV4Schema.optional(),
})

export const CyclotronInvocationQueueParametersEmailSchema = z.object({
    type: z.literal('email'),
    to: z.object({
        email: z.string(),
        name: z.string().optional(),
    }),
    replyTo: z.string().optional(),
    from: z.object({
        integrationId: z.number(),
    }),
    cc: z.string().optional(),
    bcc: z.string().optional(),
    subject: z.string(),
    preheader: z.string().optional(),
    text: z.string(),
    html: z.string(),
})

export const CyclotronInvocationQueueParametersSendPushNotificationSchema = z.object({
    type: z.literal('sendPushNotification'),
    integrationId: z.number(),
    distinctId: z.string(),
    payload: PushNotificationPayloadSchema,
    max_tries: z.number().optional(),
    timeoutMs: z.number().optional(),
})

export type PushNotificationPayloadType = z.infer<typeof PushNotificationPayloadSchema>

export type CyclotronInvocationQueueParametersFetchAwsSigV4Type = z.infer<
    typeof CyclotronInvocationQueueParametersFetchAwsSigV4Schema
>
export type CyclotronInvocationQueueParametersFetchType = z.infer<typeof CyclotronInvocationQueueParametersFetchSchema>
export type CyclotronInvocationQueueParametersEmailType = z.infer<typeof CyclotronInvocationQueueParametersEmailSchema>
export type CyclotronInvocationQueueParametersSendPushNotificationType = z.infer<
    typeof CyclotronInvocationQueueParametersSendPushNotificationSchema
>

export type CyclotronInvocationQueueParametersType =
    | CyclotronInvocationQueueParametersFetchType
    | CyclotronInvocationQueueParametersEmailType
    | CyclotronInvocationQueueParametersSendPushNotificationType
