import { dayjs } from 'lib/dayjs'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { fullName } from 'lib/utils'

import { ActivityScope, InsightShortId, PersonType, UserBasicType } from '~/types'

export interface ActivityChange {
    type: ActivityScope
    action: 'changed' | 'created' | 'deleted' | 'exported' | 'split'
    field?: string
    before?: string | number | any[] | Record<string, any> | boolean | null
    after?: string | number | any[] | Record<string, any> | boolean | null
}

export interface PersonMerge {
    type: 'Person'
    source: PersonType[]
    target: PersonType
}

export interface Trigger {
    job_type: string
    job_id: string
    payload: Record<string, any>
}

export interface ActivityLogDetail {
    merge: PersonMerge | null
    trigger: Trigger | null
    changes: ActivityChange[] | null
    name: string | null
    short_id?: InsightShortId | null
    /** e.g. for property definition carries event, person, or group */
    type?: string
    context?: Record<string, any> | null
}

export type ActivityLogItem = {
    user?: Pick<UserBasicType, 'email' | 'first_name' | 'last_name'>
    activity: string
    created_at: string
    scope: ActivityScope | string
    item_id?: string
    detail: ActivityLogDetail
    /** Present if the log is used as a notification. Whether the notification is unread. */
    unread?: boolean
    /** Whether the activity was initiated by a PostHog staff member impersonating a user. */
    is_staff?: boolean
    /** Whether the activity was initiated by the PostHog backend. Example: an exported image when sharing an insight. */
    is_system?: boolean
}

// the description of a single activity log is a sentence describing one or more changes that makes up the entry
export type Description = string | JSX.Element | null
// the extended description gives extra context, like the insight details card to describe a change to an insight
export type ExtendedDescription = JSX.Element | undefined
export type ChangeMapping = {
    description: Description[] | null
    extendedDescription?: ExtendedDescription
    suffix?: string | JSX.Element | null // to override the default suffix
}
export type HumanizedChange = { description: Description | null; extendedDescription?: ExtendedDescription }

export type HumanizedActivityLogItem = {
    email?: string | null
    name?: string
    isSystem?: boolean
    description: Description
    extendedDescription?: ExtendedDescription // e.g. an insight's filters summary
    created_at: dayjs.Dayjs
    unread?: boolean
    // used when showing e.g. diff of changes
    unprocessed?: ActivityLogItem
}

export type Describer = (logItem: ActivityLogItem, asNotification?: boolean) => HumanizedChange

export function detectBoolean(candidate: unknown): boolean {
    let b: boolean = !!candidate
    if (typeof candidate === 'string') {
        b = candidate.toLowerCase() === 'true'
    }
    return b
}

export function humanize(
    results: ActivityLogItem[],
    describerFor?: (logItem?: ActivityLogItem) => Describer | undefined,
    asNotification?: boolean
): HumanizedActivityLogItem[] {
    const logLines: HumanizedActivityLogItem[] = []

    for (const logItem of results) {
        if (!logItem.detail || !logItem.scope) {
            // Sometimes we can end up with bad payloads from the backend so we check for some required fields here
            continue
        }
        const describer = describerFor?.(logItem)

        if (!describer) {
            continue
        }
        const { description, extendedDescription } = describer(logItem, asNotification)

        if (description !== null) {
            logLines.push({
                email: logItem.user?.email,
                name: logItem.user ? fullName(logItem.user) : undefined,
                isSystem: logItem.is_system,
                description,
                extendedDescription,
                created_at: dayjs(logItem.created_at),
                unread: logItem.unread,
                unprocessed: logItem,
            })
        }
    }
    return logLines
}

export function userNameForLogItem(logItem: ActivityLogItem): string {
    if (logItem.is_system) {
        return 'PostHog'
    }
    return logItem.user ? fullName(logItem.user) : 'A user'
}

const NO_PLURAL_SCOPES: ActivityScope[] = [ActivityScope.DATA_MANAGEMENT]

const SCOPE_DISPLAY_NAMES: Partial<Record<ActivityScope, { singular: string; plural: string }>> = {
    [ActivityScope.ALERT_CONFIGURATION]: { singular: 'Alert', plural: 'Alerts' },
    [ActivityScope.BATCH_EXPORT]: { singular: 'Destination', plural: 'Destinations' },
    [ActivityScope.EXTERNAL_DATA_SOURCE]: { singular: 'Source', plural: 'Sources' },
    [ActivityScope.HOG_FUNCTION]: { singular: 'Data pipeline', plural: 'Data pipelines' },
}

export function humanizeScope(scope: ActivityScope | string, singular = false): string {
    const customName = SCOPE_DISPLAY_NAMES[scope as ActivityScope]
    if (customName) {
        return singular ? customName.singular : customName.plural
    }

    // Default behavior: split camelCase and add plural 's'
    let output = scope.split(/(?=[A-Z])/).join(' ')

    if (!singular && !NO_PLURAL_SCOPES.includes(scope as ActivityScope)) {
        output += 's'
    }

    return output
}

export function humanizeActivity(activity: string): string {
    activity = activity.replace('_', ' ')

    return activity.charAt(0).toUpperCase() + activity.slice(1)
}

export function defaultDescriber(
    logItem: ActivityLogItem,
    asNotification = false,
    resource?: string | JSX.Element
): HumanizedChange {
    resource = resource || logItem.detail.name || `a ${humanizeScope(logItem.scope, true)}`

    if (logItem.activity == 'deleted') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> deleted <b>{resource}</b>
                </>
            ),
        }
    }

    if (logItem.activity == 'created') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> created <b>{resource}</b>
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> updated <b>{resource}</b>
                </>
            ),
        }
    }

    if (logItem.activity == 'commented') {
        let description: JSX.Element | string

        if (logItem.scope === 'Comment') {
            description = (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> replied to a {humanizeScope(logItem.scope, true)}
                </>
            )
        } else {
            description = (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> commented
                    {asNotification ? <> on a {humanizeScope(logItem.scope, true)}</> : null}
                </>
            )
        }
        const commentContent = logItem.detail.changes?.[0].after as string | undefined

        return {
            description,
            extendedDescription: commentContent ? (
                <div className="border rounded bg-surface-primary p-4">
                    <LemonMarkdown lowKeyHeadings>{commentContent}</LemonMarkdown>
                </div>
            ) : undefined,
        }
    }

    return { description: null }
}
