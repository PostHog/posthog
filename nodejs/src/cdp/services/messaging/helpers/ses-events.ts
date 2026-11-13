import { z } from 'zod'

const SesMailSchema = z.object({
    timestamp: z.string(),
    source: z.string(), // From address
    messageId: z.string(),
    destination: z.array(z.string()),
    headersTruncated: z.boolean().optional(),
    headers: z.array(z.object({ name: z.string(), value: z.string() })).optional(),
    commonHeaders: z
        // A `to` of another shape only turns off the status update, never the whole record.
        .object({ subject: z.string().optional(), to: z.array(z.string()).nullish().catch(undefined) })
        .passthrough()
        .optional(),
    tags: z.record(z.string(), z.array(z.string())).optional(), // your message tags: { user_id: ["u_123"] }
})

const SesCommonEventBase = z.object({
    eventType: z.enum([
        'Send',
        'Reject',
        'Bounce',
        'Complaint',
        'Delivery',
        'Open',
        'Click',
        'RenderingFailure',
        'DeliveryDelay',
    ]),
    mail: SesMailSchema,
})

const SesOpenEventSchema = SesCommonEventBase.extend({
    eventType: z.literal('Open'),
    open: z.object({
        ipAddress: z.string().optional(),
        userAgent: z.string().optional(),
        timestamp: z.string(),
    }),
})

const SesClickEventSchema = SesCommonEventBase.extend({
    eventType: z.literal('Click'),
    click: z.object({
        ipAddress: z.string().optional(),
        link: z.string(),
        // Echoes the `ses:tags` we set on each anchor at send time, as {name: [value]}.
        // Some SES Click events send `null` here instead of omitting the field.
        linkTags: z.record(z.string(), z.array(z.string())).nullish(),
        userAgent: z.string().optional(),
        timestamp: z.string(),
    }),
})

const SesDeliveryEventSchema = SesCommonEventBase.extend({
    eventType: z.literal('Delivery'),
    delivery: z.object({
        processingTimeMillis: z.number().optional(),
        smtpResponse: z.string().optional(),
        reportingMTA: z.string().optional(),
        timestamp: z.string(),
        recipients: z.array(z.string()).optional(),
    }),
})

const SesBounceEventSchema = SesCommonEventBase.extend({
    eventType: z.literal('Bounce'),
    bounce: z.object({
        bounceType: z.enum(['Undetermined', 'Permanent', 'Transient']),
        bounceSubType: z.string().optional(),
        bouncedRecipients: z.array(
            z.object({
                emailAddress: z.string(),
                action: z.string().optional(),
                status: z.string().optional(),
                diagnosticCode: z.string().optional(),
            })
        ),
        timestamp: z.string(),
        reportingMTA: z.string().optional(),
    }),
})

export type SesBounce = z.infer<typeof SesBounceEventSchema>['bounce']

const SesComplaintEventSchema = SesCommonEventBase.extend({
    eventType: z.literal('Complaint'),
    complaint: z.object({
        complainedRecipients: z.array(z.object({ emailAddress: z.string() })),
        timestamp: z.string(),
        complaintFeedbackType: z.string().optional(),
        userAgent: z.string().optional(),
        feedbackId: z.string().optional(),
    }),
})

const SesRenderingFailureSchema = SesCommonEventBase.extend({
    eventType: z.literal('RenderingFailure'),
    renderingFailure: z.object({
        errorMessage: z.string(),
        templateName: z.string().optional(),
    }),
})

const SesSendEventSchema = SesCommonEventBase.extend({ eventType: z.literal('Send') })
const SesRejectEventSchema = SesCommonEventBase.extend({
    eventType: z.literal('Reject'),
    reject: z.object({ reason: z.string().optional() }).optional(),
})

// Acknowledged so SNS doesn't retry forever; details aren't surfaced.
const SesDeliveryDelayEventSchema = SesCommonEventBase.extend({ eventType: z.literal('DeliveryDelay') })

export const SesEventRecordSchema = z.union([
    SesOpenEventSchema,
    SesClickEventSchema,
    SesDeliveryEventSchema,
    SesBounceEventSchema,
    SesComplaintEventSchema,
    SesRenderingFailureSchema,
    SesSendEventSchema,
    SesRejectEventSchema,
    SesDeliveryDelayEventSchema,
])

export const SesEventBatchSchema = z.array(SesEventRecordSchema)

export type SesEventRecord = z.infer<typeof SesEventRecordSchema>

const MAX_SES_FIELD_LENGTH = 1024

export const sanitizeSesField = (value: string, max = MAX_SES_FIELD_LENGTH): string => {
    const cleaned = value
        .replace(/[\u0000-\u001f\u007f]/g, ' ')
        .replace(/\[/g, '(')
        .replace(/\]/g, ')')
    return cleaned.length > max ? cleaned.slice(0, max) + '…' : cleaned
}
