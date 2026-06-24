// Canonical analytics event names for the account custom-property configuration surface.
// Every `posthog.capture` in this directory must reference these — a mistyped string
// silently forks a new event in PostHog and breaks reporting without any error.
export const CustomPropertyEvents = {
    Created: 'customer analytics custom property created',
    Updated: 'customer analytics custom property updated',
    Deleted: 'customer analytics custom property deleted',
} as const
