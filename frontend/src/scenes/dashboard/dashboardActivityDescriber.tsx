import posthog from 'posthog-js'
import { DashboardFilter, HogQLVariable } from 'src/queries/schema/schema-general'

import { Link } from '@posthog/lemon-ui'
import {
    DASHBOARD_GRID_COMPACTION_LABELS,
    DASHBOARD_TILE_SPACING_LABELS,
} from '@posthog/products-dashboards/frontend/dashboardCustomization'

import {
    ActivityChange,
    ActivityLogItem,
    ActivityLogSummary,
    ActivityLogUserName,
    ChangeMapping,
    Description,
    HumanizedChange,
    defaultDescriber,
    detectBoolean,
} from 'lib/components/ActivityLog/humanizeActivity'
import {
    describeDescriptionChange,
    describeTagChanges,
} from 'lib/components/ActivityLog/activityDescriptions/changeDescriptions'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import {
    BreakdownSummary,
    DateRangeSummary,
    PropertiesSummary,
    VariablesSummary,
} from 'lib/components/Cards/InsightCard/InsightDetails'
import { isKeyOf } from 'lib/utils/guards'
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

function dashboardSummary(logItem: ActivityLogItem, action: Description, preview?: string): ActivityLogSummary {
    return {
        actor: <ActivityLogUserName logItem={logItem} />,
        action,
        target: <>Dashboard · {nameAndLink(logItem)}</>,
        preview,
    }
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
            summary: ['renamed the dashboard'],
        }
    },
    deleted: function onSoftDelete(change, logItem, asNotification) {
        const isDeleted = detectBoolean(change?.after)
        const describeChange = isDeleted ? 'deleted' : 'restored'
        return {
            description: [
                <>
                    {describeChange}
                    {asNotification && ' the dashboard '}
                </>,
            ],
            suffix: <>{nameAndLink(logItem)}</>,
            summary: [`${describeChange} the dashboard`],
        }
    },
    description: function onDescription(change, _, asNotification) {
        return {
            description: describeDescriptionChange(change, asNotification, 'dashboard'),
            summary: [change?.after ? 'updated the description' : 'removed the description'],
            preview: typeof change?.after === 'string' ? change.after : undefined,
        }
    },
    tags: describeTagChanges,
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
            summary: [isFavoriteAfter ? 'pinned the dashboard' : 'unpinned the dashboard'],
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
    folder: () => null,
    file_system_id: () => null,
    file_system_path: () => null,
    is_shared: () => null,
    creation_mode: () => null,
    user_access_level: () => null,
    _highlight: () => null,
    last_refresh: () => null,
    tiles: () => null,
    last_viewed_at: () => null,
    quick_filter_ids: () => null,
    customization: function onChangedCustomization(change) {
        const before = change?.before as DashboardType['customization']
        const after = change?.after as DashboardType['customization']
        const description: Description[] = []
        if (after?.layout_compaction && after.layout_compaction !== before?.layout_compaction) {
            description.push(
                <>
                    changed tile movement to{' '}
                    <strong>{DASHBOARD_GRID_COMPACTION_LABELS[after.layout_compaction]}</strong>
                </>
            )
        }
        if (after?.tile_spacing && after.tile_spacing !== before?.tile_spacing) {
            if (description.length > 0) {
                description.push(' and ')
            }
            description.push(
                <>
                    changed tile density to <strong>{DASHBOARD_TILE_SPACING_LABELS[after.tile_spacing]}</strong>
                </>
            )
        }
        return description.length > 0 ? { description } : null
    },
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
                    <ActivityLogUserName logItem={logItem} /> created the dashboard {nameAndLink(logItem)}
                </>
            ),
            summary: dashboardSummary(logItem, 'Created the dashboard'),
        }
    }

    if (logItem.activity == 'updated') {
        let changes: Description[] = []
        let summaryChanges: Description[] = []
        let preview: string | undefined
        let extendedDescription: JSX.Element | undefined
        let changeSuffix: Description = (
            <>
                on {asNotification && ' the dashboard '}
                {nameAndLink(logItem)}
            </>
        )

        try {
            for (const change of logItem.detail.changes || []) {
                if (!change?.field || !isKeyOf(change.field, dashboardActionsMapping)) {
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
                    summaryChanges = summaryChanges.concat(processedChange.summary ?? description)
                    preview = processedChange.preview ?? preview
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
                        prefix={<ActivityLogUserName logItem={logItem} />}
                        suffix={changeSuffix}
                    />
                ),
                summary: dashboardSummary(logItem, <SentenceList listParts={summaryChanges} />, preview),
                extendedDescription,
            }
        }
    }

    if (logItem.activity === 'sharing enabled') {
        return {
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> shared {asNotification ? 'your' : 'the'} dashboard{' '}
                    {nameAndLink(logItem)}
                </>
            ),
            summary: dashboardSummary(logItem, 'Shared the dashboard'),
        }
    }

    if (logItem.activity === 'sharing disabled') {
        return {
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> deleted shared link for {asNotification ? 'your' : 'the'}{' '}
                    dashboard {nameAndLink(logItem)}
                </>
            ),
            summary: dashboardSummary(logItem, 'Deleted the shared link'),
        }
    }

    if (logItem.activity === 'access token refreshed') {
        return {
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> refreshed the shared link for{' '}
                    {asNotification ? 'your' : 'the'} dashboard {nameAndLink(logItem)}
                </>
            ),
            summary: dashboardSummary(logItem, 'Refreshed the shared link'),
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
