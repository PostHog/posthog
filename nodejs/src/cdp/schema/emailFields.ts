import { z } from 'zod'

// Django refuses these with a reason before the send is queued. The worker checks again, because a
// header PostHog sets itself, or a line break in a value, must never reach a provider from any path.
const HEADERS_POSTHOG_SETS = new Set([
    'auto-submitted',
    'bcc',
    'cc',
    'date',
    'dkim-signature',
    'from',
    'message-id',
    'mime-version',
    'received',
    'reply-to',
    'return-path',
    'sender',
    'subject',
    'to',
])
const HEADER_PREFIXES_POSTHOG_SETS = ['content-', 'x-posthog-', 'x-ses-']

export const MAX_EMAIL_HEADERS = 10
export const MAX_EMAIL_TAGS = 10
export const RESERVED_EMAIL_TAG_PREFIX = 'ph_'

const isHeaderPostHogSets = (name: string): boolean => {
    const lowered = name.toLowerCase()
    return (
        HEADERS_POSTHOG_SETS.has(lowered) || HEADER_PREFIXES_POSTHOG_SETS.some((prefix) => lowered.startsWith(prefix))
    )
}

export const EmailHeaderSchema = z.object({
    name: z
        .string()
        .regex(/^[!-9;-~]{1,126}$/)
        .refine((name) => !isHeaderPostHogSets(name), 'PostHog sets this header itself'),
    value: z.string().regex(/^[ -~]{0,870}$/),
})

// Django's bare-address grammar, so the worker takes every copy Django accepts and none that names a second recipient.
export const BareEmailAddressSchema = z
    .string()
    .regex(/^[^\s@"<>,;:()[\]\\]+@[^\s@"<>,;:()[\]\\]+\.[^\s@"<>,;:()[\]\\]+$/)

const TagPart = z.string().regex(/^[A-Za-z0-9_-]{1,256}$/)

export const EmailTagSchema = z.object({
    name: TagPart.refine(
        (name) => !name.toLowerCase().startsWith(RESERVED_EMAIL_TAG_PREFIX),
        'PostHog reserves tag names that start with ph_'
    ),
    value: TagPart,
})

export type EmailHeader = z.infer<typeof EmailHeaderSchema>
export type EmailTag = z.infer<typeof EmailTagSchema>
