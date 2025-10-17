import posthog from 'posthog-js'
import { DashboardFilter, HogQLVariable } from 'src/queries/schema/schema-general'

import { Link } from '@posthog/lemon-ui'

import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
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
import {
    BreakdownSummary,
    DateRangeSummary,
    PropertiesSummary,
    VariablesSummary,
} from 'lib/components/Cards/InsightCard/InsightDetails'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { pluralize } from 'lib/utils'
import { urls } from 'scenes/urls'

import { DashboardType } from '~/types'

function nameAndLink(logItem?: ActivityLogItem): JSX.Element {
    return logItem?.item_id ? (
        <Link to={urls.dashboard(logItem.item_id)}>{logItem?.detail?.name || 'Unknown dashboard'}</Link>
    ) : logItem?.detail?.name ? (
        <>{logItem.detail.name}</>
    ) : (
        <i>Unknown dashboard</i>
    )
}

const dashboardActionsMapping: Record<
    keyof DashboardType,
    (change?: ActivityChange, logItem?: ActivityLogItem, asNotification?: boolean) => ChangeMapping | null
> = {
    name: function onName(change, logItem, asNotification) {
        return {
            description: [
                <>
                    renamed {asNotification && 'the dashboard '}"{change?.before}" to{' '}
                    <strong>"{nameAndLink(logItem)}"</strong>
                </>,
            ],
            suffix: <></>,
        }
    },
    deleted: function onSoftDelete(change, logItem, asNotification) {
        const isDeleted = detectBoolean(change?.after)
        const describeChange = isDeleted ? 'deleted' : 'un-deleted'
        return {
            description: [
                <>
                    {describeChange}
                    {asNotification && ' the dashboard '}
                </>,
            ],
            suffix: <>{nameAndLink(logItem)}</>,
        }
    },
    description: function onDescription(change, _, asNotification) {
        return {
            description: [
                <>
                    changed the description {asNotification && ' of the dashboard '}to{' '}
                    <strong>"{change?.after as string}"</strong>
                </>,
            ],
        }
    },
    tags: function onTags(change) {
        const tagsBefore = change?.before as string[]
        const tagsAfter = change?.after as string[]
        const addedTags = tagsAfter.filter((t) => tagsBefore.indexOf(t) === -1)
        const removedTags = tagsBefore.filter((t) => tagsAfter.indexOf(t) === -1)

        const changes: Description[] = []
        if (addedTags.length) {
            changes.push(
                <>
                    added {pluralize(addedTags.length, 'tag', 'tags', false)}{' '}
                    <ObjectTags tags={addedTags} saving={false} style={{ display: 'inline' }} staticOnly />
                </>
            )
        }
        if (removedTags.length) {
            changes.push(
                <>
                    removed {pluralize(removedTags.length, 'tag', 'tags', false)}{' '}
                    <ObjectTags tags={removedTags} saving={false} style={{ display: 'inline' }} staticOnly />
                </>
            )
        }

        return { description: changes }
    },
    pinned: function onPinned(change, logItem, asNotification) {
        const isFavoriteAfter = detectBoolean(change?.after)
        return {
            description: [
                <>
                    <div className="highlighted-activity">
                        {isFavoriteAfter ? '' : 'un-'}pinned{asNotification && ' the dashboard '}
                    </div>
                </>,
            ],
            suffix: <>{nameAndLink(logItem)}</>,
        }
    },
    filters: function onChangedFilters(change, logItem) {
        const filtersAfter = change?.after as DashboardFilter
        return {
            description: ['changed the dashboard filters'],
            extendedDescription: (
                <div className="ActivityDescription">
                    <PropertiesSummary properties={filtersAfter.properties} />
                    <BreakdownSummary breakdownFilter={filtersAfter.breakdown_filter} />
                    <DateRangeSummary dateFrom={filtersAfter.date_from} dateTo={filtersAfter.date_to} />
                </div>
            ),
            suffix: <>on the dashboard {nameAndLink(logItem)} to</>,
        }
    },
    variables: function onChangedVariables(change, logItem) {
        const variablesAfter = change?.after as Record<string, HogQLVariable>
        return {
            description: ['changed the dashboard variables'],
            extendedDescription: (
                <div className="ActivityDescription">
                    <VariablesSummary variables={variablesAfter} />
                </div>
            ),
            suffix: <>on the dashboard {nameAndLink(logItem)} to</>,
        }
    },
    id: () => null,
    created_at: () => null,
    created_by: () => null,
    persisted_filters: () => null,
    persisted_variables: () => null,
    breakdown_colors: () => null,
    data_color_theme_id: () => null,
    last_accessed_at: () => null,
    is_shared: () => null,
    creation_mode: () => null,
    user_access_level: () => null,
    _highlight: () => null,
    last_refresh: () => null,
    tiles: () => null,
}

export function dashboardActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope != 'Dashboard') {
        console.error('dashboard describer received a non-dashboard activity')
        return { description: null }
    }

    if (logItem.activity == 'created') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> created the dashboard {nameAndLink(logItem)}
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        let changes: Description[] = []
        let extendedDescription: JSX.Element | undefined
        let changeSuffix: Description = (
            <>
                on {asNotification && ' the dashboard '}
                {nameAndLink(logItem)}
            </>
        )

        try {
            for (const change of logItem.detail.changes || []) {
                if (!change?.field || !dashboardActionsMapping[change.field]) {
                    continue // dashboard updates have to have a "field" to be described
                }

                const actionHandler = dashboardActionsMapping[change.field]
                const processedChange = actionHandler(change, logItem, asNotification)
                if (processedChange === null) {
                    continue // // unexpected log from backend is indescribable
                }

                const { description, extendedDescription: _extendedDescription, suffix } = processedChange
                if (description) {
                    changes = changes.concat(description)
                }
                if (_extendedDescription) {
                    extendedDescription = _extendedDescription
                }
                if (suffix) {
                    changeSuffix = suffix
                }
            }
        } catch (e) {
            console.error('Error while summarizing dashboard update', e)
            posthog.captureException(e)
        }

        if (changes.length) {
            return {
                description: (
                    <SentenceList
                        listParts={changes}
                        prefix={<strong>{userNameForLogItem(logItem)}</strong>}
                        suffix={changeSuffix}
                    />
                ),
                extendedDescription,
            }
        }
    }

    if (logItem.activity === 'share_login_success') {
        const afterData = logItem.detail.changes?.[0]?.after as any
        const clientIp = afterData?.client_ip || 'unknown IP'
        const passwordNote = afterData?.password_note || 'unknown password'

        return {
            description: (
                <>
                    <strong>Anonymous user</strong> successfully authenticated to shared dashboard{' '}
                    <b>{nameAndLink(logItem)}</b> from {clientIp} using password <strong>{passwordNote}</strong>
                </>
            ),
        }
    }

    if (logItem.activity === 'share_login_failed') {
        const afterData = logItem.detail.changes?.[0]?.after as any
        const clientIp = afterData?.client_ip || 'unknown IP'

        return {
            description: (
                <>
                    <strong>Anonymous user</strong> failed to authenticate to shared dashboard{' '}
                    <b>{nameAndLink(logItem)}</b> from {clientIp}
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification, nameAndLink(logItem))
}
