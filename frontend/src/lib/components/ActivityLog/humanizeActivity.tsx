import { dayjs } from 'lib/dayjs'

export interface ActivityChange {
    type: 'FeatureFlag'
    action: 'changed' | 'created' | 'deleted'
    field?: string
    before?: string | Record<string, any> | boolean
    after?: string | Record<string, any> | boolean
}

export interface ActivityLogDetail {
    changes: ActivityChange[] | null
    name: string
}

export interface ActivityUser {
    email: string
    first_name: string
}

export enum ActivityScope {
    FEATURE_FLAG = 'FeatureFlag',
}

export interface ActivityLogItem {
    user: ActivityUser
    activity: string
    created_at: string
    scope: ActivityScope
    item_id?: string
    detail: ActivityLogDetail
}

export interface HumanizedActivityLogItem {
    email?: string
    name?: string
    description: string | JSX.Element
    created_at: dayjs.Dayjs
}

type Describer = (logItem: ActivityLogItem) => (string | JSX.Element | null)[]
const registeredDescribers: Record<ActivityScope, Describer> = {
    [ActivityScope.FEATURE_FLAG]: () => [],
}

/*
In order to use existing components to describe things without this humanizer depending on many parts of the front end
Things being described can register a describer here.
Keeping dependencies pointing into the activity log component, not out of it
 */
export function registerActivityDescriptions(registration: {
    describer: (logItem: ActivityLogItem) => (string | JSX.Element | null)[]
    scope: ActivityScope
}): void {
    registeredDescribers[registration.scope] = registration.describer
}

export function humanize(results: ActivityLogItem[]): HumanizedActivityLogItem[] {
    return (results || []).reduce((acc, logItem) => {
        const describerForScope: Describer = registeredDescribers[logItem.scope]
        if (!describerForScope) {
            return acc
        }
        describerForScope(logItem).forEach((description) => {
            if (description !== null) {
                acc.push({
                    email: logItem.user.email,
                    name: logItem.user.first_name,
                    description: description,
                    created_at: dayjs(logItem.created_at),
                })
            }
        })

        return acc
    }, [] as HumanizedActivityLogItem[])
}
