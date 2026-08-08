// A run's terminal error, mapped to failure-banner copy. The onboarding cloud run can die on a
// gateway 403, and the LLM gateway hands back the provider's raw body, which names no cause to a
// brand-new user. Map the ones we recognize to a cause and a next step, and fall back to a generic
// line rather than the raw provider string for anything else.

export interface InstallationError {
    title: string
    detail: string | null
}

// The 403 the gateway returns when the run's model needs a paid plan.
const MODEL_GATE_PATTERNS = ['needs a paid posthog plan']

// The 403s the gateway returns when the organization's free AI usage is spent.
const ORG_LIMIT_PATTERNS = [
    'reached its posthog code usage limit',
    'reached its usage limit for this billing period',
    'user burst rate limit exceeded',
    'user sustained rate limit exceeded',
]

// A 403 that a Cloudflare Workers AI model returns and the gateway passes through unmapped.
const PROVIDER_TOS_PATTERNS = ['violation of provider terms of service']

// Shared tail: every recognized failure keeps the manual install open as a fallback.
const MANUAL_FALLBACK = 'You can also install PostHog yourself with the steps below.'

function includesAny(value: string, patterns: readonly string[]): boolean {
    const lower = value.toLowerCase()
    return patterns.some((pattern) => lower.includes(pattern))
}

export function installationErrorCopy(rawMessage: string | null, cancelled: boolean): InstallationError {
    // A cancel is a deliberate stop, not a broken install, and never carries a gateway 403, so keep
    // its own reason verbatim.
    if (cancelled) {
        return { title: 'Run cancelled', detail: rawMessage }
    }

    const message = rawMessage ?? ''

    if (includesAny(message, MODEL_GATE_PATTERNS)) {
        return {
            title: 'Add a payment method to keep going',
            detail: `Automated setup uses an AI model that needs a paid PostHog plan. Add a payment method to your organization and start setup again. ${MANUAL_FALLBACK}`,
        }
    }

    if (includesAny(message, ORG_LIMIT_PATTERNS)) {
        return {
            title: 'Usage limit reached',
            detail: `Your organization has used up its included AI usage. Add a payment method or raise your limit, then start setup again. ${MANUAL_FALLBACK}`,
        }
    }

    if (includesAny(message, PROVIDER_TOS_PATTERNS)) {
        return {
            title: 'The AI provider blocked setup',
            detail: `The AI provider we use for automated setup rejected the request. Start setup again. ${MANUAL_FALLBACK}`,
        }
    }

    return {
        title: 'Installation failed',
        // Never surface the raw provider string to a new user; a message we don't recognize still
        // means the run failed, so guide them to the same recovery.
        detail: rawMessage ? `Automated setup ran into a problem. Start setup again. ${MANUAL_FALLBACK}` : null,
    }
}
