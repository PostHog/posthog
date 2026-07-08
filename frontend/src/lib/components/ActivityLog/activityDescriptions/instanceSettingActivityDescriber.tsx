import {
    ActivityLogItem,
    Describer,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'

import { ActivityScope } from '~/types'

// Kept in sync with the sentinels the backend records in posthog/api/instance_settings.py.
const REDACTED = '<redacted>'
const UNSET = '<unset>'

// Secret settings are never logged in cleartext — the backend records these
// sentinels instead of the value. Translate the before/after sentinel pair into
// the operation that happened so the audit line is legible without exposing the
// raw markers. Returns null for any non-secret transition.
const describeSecretTransition = (before: unknown, after: unknown): string | null => {
    if (before === UNSET && after === REDACTED) {
        return 'set'
    }
    if (before === REDACTED && after === REDACTED) {
        return 'rotated'
    }
    if (before === REDACTED && after === UNSET) {
        return 'cleared'
    }
    return null
}

const isSentinel = (value: unknown): boolean => value === REDACTED || value === UNSET

export const instanceSettingActivityDescriber: Describer = (
    logItem: ActivityLogItem,
    asNotification?: boolean
): HumanizedChange => {
    if (logItem.scope !== ActivityScope.INSTANCE_SETTING || logItem.activity !== 'updated') {
        return defaultDescriber(logItem, asNotification)
    }

    const change = logItem.detail.changes?.[0]
    if (!change) {
        return defaultDescriber(logItem, asNotification)
    }

    const key = change.field || logItem.detail.name || 'unknown setting'
    const transition = describeSecretTransition(change.before, change.after)
    const actor = <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong>

    if (transition) {
        return {
            description: (
                <>
                    {actor} {transition} instance setting <code>{key}</code>
                </>
            ),
        }
    }

    // A secret transition we don't have a verb for: render a generic line rather than
    // echo the raw sentinel into the audit log.
    if (isSentinel(change.before) || isSentinel(change.after)) {
        return {
            description: (
                <>
                    {actor} updated instance setting <code>{key}</code>
                </>
            ),
        }
    }

    return {
        description: (
            <>
                {actor} changed instance setting <code>{key}</code> from <code>{JSON.stringify(change.before)}</code> to{' '}
                <code>{JSON.stringify(change.after)}</code>
            </>
        ),
    }
}
