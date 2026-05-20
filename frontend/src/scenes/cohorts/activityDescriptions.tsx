import '../../lib/components/Cards/InsightCard/InsightCard.scss'

import {
    ActivityChange,
    ActivityLogItem,
    ChangeMapping,
    Description,
    HumanizedChange,
    defaultDescriber,
    detectBoolean,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
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
            return { description: [<>added a description</>] }
        }
        if (before && !after) {
            return { description: [<>cleared the description</>] }
        }
        return { description: [<>updated the description</>] }
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

export function cohortActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope != 'Cohort') {
        console.error('cohort describer received a non-cohort activity')
        return { description: null }
    }

    const actor = <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong>
    const cohortLink = nameOrLinkToCohort(logItem?.item_id, logItem?.detail.name)

    if (logItem.activity == 'created') {
        return {
            description: (
                <>
                    {actor} created the cohort: {cohortLink}
                </>
            ),
        }
    }

    if (logItem.activity == 'deleted') {
        return {
            description: (
                <>
                    {actor} deleted the cohort: {cohortLink}
                </>
            ),
        }
    }

    if (logItem.activity == 'restored') {
        return {
            description: (
                <>
                    {actor} restored the cohort: {cohortLink}
                </>
            ),
        }
    }

    if (logItem.activity == 'persons_added_manually') {
        return {
            description: (
                <>
                    {actor} added users to the cohort: {cohortLink}
                </>
            ),
        }
    }

    if (logItem.activity == 'person_removed_manually') {
        return {
            description: (
                <>
                    {actor} removed a user from the cohort: {cohortLink}
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        const detailChanges = logItem.detail.changes || []
        // is_static and cohort_type both render as "changed the cohort type to X" — when a flip
        // co-emits both, drop is_static so we don't print the line twice.
        const fieldsPresent = new Set(detailChanges.map((c) => c?.field))
        const changes: Description[] = []
        for (const change of detailChanges) {
            if (!change?.field) {
                continue
            }
            if (change.field === 'is_static' && fieldsPresent.has('cohort_type')) {
                continue
            }
            const handler = cohortFieldMapping[change.field]
            const result = handler ? handler(change) : null
            if (result?.description) {
                changes.push(...result.description)
            } else if (!handler) {
                // unknown field — surface it generically rather than dumping JSON
                changes.push(
                    <>
                        updated <strong>{change.field}</strong>
                    </>
                )
            }
        }

        if (changes.length) {
            return {
                description: (
                    <SentenceList
                        listParts={changes}
                        prefix={actor}
                        suffix={
                            <>
                                on {asNotification ? 'the cohort ' : ''}
                                {cohortLink}
                            </>
                        }
                    />
                ),
            }
        }

        return {
            description: (
                <>
                    {actor} updated the cohort: {cohortLink}
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification, cohortLink)
}
