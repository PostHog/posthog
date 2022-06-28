import { dayjs } from 'lib/dayjs'
import { InsightShortId, PersonType } from '~/types'

export interface ActivityChange {
    type: 'FeatureFlag' | 'Person' | 'Insight'
    action: 'changed' | 'created' | 'deleted' | 'exported' | 'split'
    field?: string
    before?: string | Record<string, any> | boolean
    after?: string | Record<string, any> | boolean
}

export interface PersonMerge {
    type: 'Person'
    source: PersonType[]
    target: PersonType
}

export interface ActivityLogDetail {
    merge: PersonMerge | null
    changes: ActivityChange[] | null
    name: string | null
    short_id?: InsightShortId | null
}

export interface ActivityUser {
    email: string
    first_name: string
}

export enum ActivityScope {
    FEATURE_FLAG = 'FeatureFlag',
    PERSON = 'Person',
    INSIGHT = 'Insight',
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

export type Describer = (logItem: ActivityLogItem) => string | JSX.Element | null

export function humanize(results: ActivityLogItem[], describer?: Describer): HumanizedActivityLogItem[] {
    if (!describer) {
        // TODO make a default describer
        return []
    }

    const logLines: HumanizedActivityLogItem[] = []

    for (const logItem of results) {
        const description = describer(logItem)
        if (description !== null) {
            logLines.push({
                email: logItem.user.email,
                name: logItem.user.first_name,
                description,
                created_at: dayjs(logItem.created_at),
            })
        }
    }
    return logLines
}
