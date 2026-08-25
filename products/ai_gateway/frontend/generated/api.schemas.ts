/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface SpendLimitApi {
    /**
     * The limit in USD as a decimal string, or null when no limit is set.
     * @nullable
     * @pattern ^-?\d{0,13}(?:\.\d{0,6})?$
     */
    limit_usd: string | null
    /**
     * Length of the accounting window the limit applies to, in seconds. The window is fixed rather than sliding: it starts at the first spend after a reset and the counter resets once per window. Null when no limit is set.
     * @nullable
     */
    window_seconds: number | null
    /** Whether spend limits are available on this PostHog deployment. False means no limit can be set here, so any limit shown in the app informs only. */
    available: boolean
}

export interface SpendLimitErrorApi {
    /** What went wrong, in a form that can be shown to a person. */
    detail: string
}

export interface SpendLimitWriteApi {
    /**
     * The limit in USD. The gateway stores the limit and, once enforcement is live for this traffic, refuses spend past it until the window resets.
     * @pattern ^-?\d{0,13}(?:\.\d{0,6})?$
     */
    limit_usd: string
    /**
     * Length of the accounting window the limit applies to, in seconds. The window is fixed rather than sliding: it starts at the first spend after a reset and the counter resets once per window. At least an hour and at most 366 days.
     * @minimum 3600
     * @maximum 31622400
     */
    window_seconds: number
}
