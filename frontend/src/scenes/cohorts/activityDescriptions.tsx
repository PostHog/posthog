import { summarizeDescriptionChange } from 'lib/components/ActivityLog/activityDescriptions/changeDescriptions'
import { describeChangeMappings } from 'lib/components/ActivityLog/activityDescriptions/describeChangeMappings'
import {
    ActivityChange,
    ActivityLogItem,
    ActivityLogUserName,
    ChangeMapping,
    HumanizedChange,
    activityLogSummary,
    defaultDescriber,
    detectBoolean,
} from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { CohortType } from '~/types'

const nameOrLinkToCohort = (id?: string | null, name?: string | null): string | JSX.Element => {
    const displayName = name || '(empty string)'
    return id ? <Link to={urls.cohort(id)}>{displayName}</Link> : displayName
}

const countCohortCriteria = (filters: CohortType['filters'] | undefined): number => {
    const groups = filters?.properties?.values ?? []
    return groups.reduce((total, group) => {
        const values = (group as { values?: unknown[] })?.values
        return total + (Array.isArray(values) ? values.length : 0)
    }, 0)
}

const cohortFieldMapping: Record<string, (change?: ActivityChange) => ChangeMapping | null> = {
    name: function onName(change) {
        const before = change?.before as string | null | undefined
        const after = change?.after as string | null | undefined
        return {
            description: [
                <>
                    renamed from <strong>{before || '(empty string)'}</strong> to{' '}
                    <strong>{after || '(empty string)'}</strong>
                </>,
            ],
        }
    },
    description: function onDescription(change) {
        const before = (change?.before as string | null | undefined) || ''
        const after = (change?.after as string | null | undefined) || ''
        if (!before && after) {
            return {
                description: [<>added a description</>],
                summary: summarizeDescriptionChange(change),
                preview: after,
            }
        }
        if (before && !after) {
            return { description: [<>cleared the description</>], summary: summarizeDescriptionChange(change) }
        }
        return {
            description: [<>updated the description</>],
            summary: summarizeDescriptionChange(change),
            preview: after,
        }
    },
    filters: function onFilters(change) {
        const before = countCohortCriteria(change?.before as CohortType['filters'])
        const after = countCohortCriteria(change?.after as CohortType['filters'])
        if (before === after) {
            return { description: [<>updated the matching criteria</>] }
        }
        return {
            description: [
                <>
                    changed the matching criteria from <strong>{before}</strong> to <strong>{after}</strong>
                </>,
            ],
        }
    },
    query: function onQuery() {
        return { description: [<>updated the cohort query</>] }
    },
    is_static: function onIsStatic(change) {
        const isStatic = detectBoolean(change?.after)
        return {
            description: [
                <>
                    changed the cohort type to <strong>{isStatic ? 'static' : 'dynamic'}</strong>
                </>,
            ],
        }
    },
    cohort_type: function onCohortType(change) {
        const after = change?.after as string | null | undefined
        if (!after) {
            return null
        }
        return {
            description: [
                <>
                    changed the cohort type to <strong>{after}</strong>
                </>,
            ],
        }
    },
    groups: function onGroups() {
        return { description: [<>updated the matching criteria</>] }
    },
    // fields that we don't want to surface (excluded on backend or noisy)
    id: () => null,
    team_id: () => null,
    deleted: () => null,
    created_by_id: () => null,
    created_at: () => null,
    last_error_at: () => null,
}

function describeCohortField(change: ActivityChange): ChangeMapping | null {
    const handler = cohortFieldMapping[change.field!]
    if (handler) {
        return handler(change)
    }
    // unknown field — surface it generically rather than dumping JSON
    return {
        description: [
            <>
                updated <strong>{change.field}</strong>
            </>,
        ],
    }
}

function describeCohortUpdate(
    logItem: ActivityLogItem,
    asNotification: boolean | undefined,
    cohortLink: string | JSX.Element
): HumanizedChange | null {
    const detailChanges = logItem.detail.changes || []
    // is_static and cohort_type both render as "changed the cohort type to X" — when a flip
    // co-emits both, drop is_static so we don't print the line twice.
    const fieldsPresent = new Set(detailChanges.map((change) => change?.field))
    const mappings = detailChanges.flatMap((change) => {
        if (!change?.field || (change.field === 'is_static' && fieldsPresent.has('cohort_type'))) {
            return []
        }
        const result = describeCohortField(change)
        return result?.description ? [result] : []
    })
    return describeChangeMappings(
        logItem,
        mappings,
        cohortLink,
        <>
            on {asNotification ? 'the cohort ' : ''}
            {cohortLink}
        </>
    )
}

export function cohortActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope != 'Cohort') {
        console.error('cohort describer received a non-cohort activity')
        return { description: null }
    }

    const actor = <ActivityLogUserName logItem={logItem} />
    const cohortLink = nameOrLinkToCohort(logItem?.item_id, logItem?.detail.name)

    if (logItem.activity == 'created') {
        return {
            summary: activityLogSummary(logItem, 'Created the cohort', cohortLink),
            description: (
                <>
                    {actor} created the cohort: {cohortLink}
                </>
            ),
        }
    }

    if (logItem.activity == 'deleted') {
        return {
            summary: activityLogSummary(logItem, 'Deleted the cohort', cohortLink),
            description: (
                <>
                    {actor} deleted the cohort: {cohortLink}
                </>
            ),
        }
    }

    if (logItem.activity == 'restored') {
        return {
            summary: activityLogSummary(logItem, 'Restored the cohort', cohortLink),
            description: (
                <>
                    {actor} restored the cohort: {cohortLink}
                </>
            ),
        }
    }

    if (logItem.activity == 'persons_added_manually') {
        return {
            summary: activityLogSummary(logItem, 'Added people to the cohort', cohortLink),
            description: (
                <>
                    {actor} added users to the cohort: {cohortLink}
                </>
            ),
        }
    }

    if (logItem.activity == 'person_removed_manually') {
        return {
            summary: activityLogSummary(logItem, 'Removed a person from the cohort', cohortLink),
            description: (
                <>
                    {actor} removed a user from the cohort: {cohortLink}
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        const changes = describeCohortUpdate(logItem, asNotification, cohortLink)
        if (changes) {
            return changes
        }
        return {
            summary: activityLogSummary(logItem, 'Updated the cohort', cohortLink),
            description: (
                <>
                    {actor} updated the cohort: {cohortLink}
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification, cohortLink)
}
