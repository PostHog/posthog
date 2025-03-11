import { DateTime } from 'luxon'

import { PropertyType } from '~/src/types'

// lifted from here:
// https://github.com/PostHog/posthog/blob/021aaab04b4acd96cf8121c033ac3b0042492598/rust/property-defs-rs/src/types.rs#L457-L461
const DJANGO_MAX_CHARFIELD_LENGTH = 200

// These properties have special meaning, and are ignored
export const PROPERTY_DEFS_PROPERTIES_TO_SKIP: string[] = [
    '$set',
    '$set_once',
    '$unset',
    '$group_0',
    '$group_1',
    '$group_2',
    '$group_3',
    '$group_4',
    '$groups',
]

export const PROPERTY_DEFS_DATE_PROP_KEYWORDS: string[] = [
    'time',
    'timestamp',
    'date',
    '_at',
    '-at',
    'createdat',
    'updatedat',
]

export function willFitInPostgres(s: string) {
    return s.length < DJANGO_MAX_CHARFIELD_LENGTH
}

export function sanitizeEventName(eventName: string) {
    return eventName.replace('\u0000', '\uFFFD')
}

export function sixMonthsAgoUnixSeconds() {
    const now = new Date()
    now.setMonth(now.getMonth() - 6)
    return Math.floor(now.getTime() / 1000)
}

export const getPropertyType = (rawKey: string, value: any): PropertyType | null => {
    const key = rawKey.trim().toLowerCase()

    // Special cases for certain property prefixes
    if (key.startsWith('utm_')) {
        // utm_ prefixed properties should always be detected as strings.
        // Sometimes the first value sent looks like a number, even though
        // subsequent values are not.
        return PropertyType.String
    }
    if (key.startsWith('$feature/')) {
        // $feature/ prefixed properties should always be detected as strings.
        // These are feature flag values, and can be boolean or string.
        // Sometimes the first value sent is boolean (because flag isn't enabled) while
        // subsequent values are not. We don't want this to be misunderstood as a boolean.
        return PropertyType.String
    }

    if (key === '$feature_flag_response') {
        // $feature_flag_response properties should always be detected as strings.
        // These are feature flag values, and can be boolean or string.
        // Sometimes the first value sent is boolean (because flag isn't enabled) while
        // subsequent values are not. We don't want this to be misunderstood as a boolean.
        return PropertyType.String
    }

    if (key.startsWith('$survey_response')) {
        // NB: $survey_responses are collected in an interesting way, where the first
        // response is called `$survey_response` and subsequent responses are called
        // `$survey_response_2`, `$survey_response_3`, etc. So, this check should auto-cast
        // all survey responses to strings.
        return PropertyType.String
    }

    if (typeof value === 'string') {
        const s = value.trim()
        if (s === 'true' || s === 'false') {
            return PropertyType.Boolean
        }
        // Try to parse this as an ISO 8601 date
        try {
            if (PROPERTY_DEFS_DATE_PROP_KEYWORDS.some((kw) => key.includes(kw))) {
                return PropertyType.DateTime
            }
            const date = DateTime.fromISO(s)
            if (date.isValid) {
                return PropertyType.DateTime
            }
            // TODO(eli): add speculative date string matching?
        } catch {
            // Not a valid date, continue to string type
        }
        return PropertyType.String
    }

    if (typeof value === 'boolean') {
        return PropertyType.Boolean
    }

    if (typeof value === 'number') {
        if (value >= sixMonthsAgoUnixSeconds()) {
            return PropertyType.DateTime
        }
        return PropertyType.Numeric
    }

    return null
}
