import { objectsEqual } from 'lib/utils/objects'

import {
    GroupingApi,
    GroupingModeEnumApi,
    PlatformAlertConfigurationApi,
    PlatformAlertConfigurationCreateApi,
    PlatformAlertConfigurationEditApi,
    PlatformAlertConfigurationSourceKindEnumApi,
    WarehouseAlertGroupByEnumApi,
} from 'products/alerts_platform/frontend/generated/api.schemas'

export type WarehouseAlertKind =
    | typeof PlatformAlertConfigurationSourceKindEnumApi.WarehouseSource
    | typeof PlatformAlertConfigurationSourceKindEnumApi.WarehouseDestination

export type WarehouseAlertGroupBy = WarehouseAlertGroupByEnumApi

export interface WarehouseAlertFormValues {
    name: string
    enabled: boolean
    /** Empty means the alert watches every source or destination, including ones added later. */
    targetIds: string[]
    groupBy: WarehouseAlertGroupBy
    includeBillingLimits: boolean
    emailProjectMembers: boolean
}

interface WarehouseAlertKindConfig {
    idsKey: 'source_ids' | 'destination_ids'
    defaultName: string
}

const KIND_CONFIG: Record<WarehouseAlertKind, WarehouseAlertKindConfig> = {
    warehouse_source: { idsKey: 'source_ids', defaultName: 'Source sync failures' },
    warehouse_destination: { idsKey: 'destination_ids', defaultName: 'Destination failures' },
}

// The backend keys each alert instance on this result label, and rejects any other grouping.
const GROUPING_KEY_BY_GROUP_BY: Record<WarehouseAlertGroupBy, string> = {
    schema: 'schema_id',
    source: 'source_id',
}
const DESTINATION_GROUPING_KEY = 'destination_id'

export function isWarehouseAlertKind(kind: string): kind is WarehouseAlertKind {
    return kind in KIND_CONFIG
}

export function newWarehouseAlertForm(kind: WarehouseAlertKind, targetIds: string[] = []): WarehouseAlertFormValues {
    return {
        name: KIND_CONFIG[kind].defaultName,
        enabled: true,
        targetIds,
        groupBy: WarehouseAlertGroupByEnumApi.Source,
        includeBillingLimits: false,
        emailProjectMembers: true,
    }
}

export function watchedIds(alert: PlatformAlertConfigurationApi): string[] {
    if (!isWarehouseAlertKind(alert.source_kind)) {
        return []
    }
    const ids = alert.source_config[KIND_CONFIG[alert.source_kind].idsKey]
    return Array.isArray(ids) ? ids.map(String) : []
}

export function alertGroupBy(alert: PlatformAlertConfigurationApi): WarehouseAlertGroupBy {
    return alert.source_config.group_by === WarehouseAlertGroupByEnumApi.Schema
        ? WarehouseAlertGroupByEnumApi.Schema
        : WarehouseAlertGroupByEnumApi.Source
}

export function emailsProjectMembers(alert: PlatformAlertConfigurationApi): boolean {
    return alert.source_config.email_project_members === true
}

/** Whether the alert covers the target. An alert with no ids watches every one. */
export function alertWatches(alert: PlatformAlertConfigurationApi, targetId: string): boolean {
    const ids = watchedIds(alert)
    return ids.length === 0 || ids.includes(targetId)
}

export function alertsForScope(
    alerts: PlatformAlertConfigurationApi[],
    kind: WarehouseAlertKind,
    targetId?: string
): PlatformAlertConfigurationApi[] {
    return alerts.filter((alert) => alert.source_kind === kind && (!targetId || alertWatches(alert, targetId)))
}

export function formValuesFromAlert(alert: PlatformAlertConfigurationApi): WarehouseAlertFormValues {
    return {
        name: alert.name,
        enabled: alert.enabled,
        targetIds: watchedIds(alert),
        groupBy: alertGroupBy(alert),
        includeBillingLimits: alert.source_config.include_billing_limits === true,
        emailProjectMembers: emailsProjectMembers(alert),
    }
}

function grouping(kind: WarehouseAlertKind, values: WarehouseAlertFormValues, current?: GroupingApi): GroupingApi {
    const key =
        kind === PlatformAlertConfigurationSourceKindEnumApi.WarehouseSource
            ? GROUPING_KEY_BY_GROUP_BY[values.groupBy]
            : DESTINATION_GROUPING_KEY
    return { ...current, mode: GroupingModeEnumApi.ByResultLabels, keys: [key] }
}

function sourceConfig(
    kind: WarehouseAlertKind,
    values: WarehouseAlertFormValues
): PlatformAlertConfigurationCreateApi['source_config'] {
    if (kind === PlatformAlertConfigurationSourceKindEnumApi.WarehouseSource) {
        return {
            source_ids: values.targetIds,
            group_by: values.groupBy,
            include_billing_limits: values.includeBillingLimits,
            email_project_members: values.emailProjectMembers,
        }
    }
    return { destination_ids: values.targetIds, email_project_members: values.emailProjectMembers }
}

// A sync status is the current state, so the backend accepts only one check per decision.
const SINGLE_CHECK = { evaluation_periods: 1, datapoints_to_alarm: 1 }

export function buildCreateBody(
    kind: WarehouseAlertKind,
    values: WarehouseAlertFormValues
): PlatformAlertConfigurationCreateApi {
    return {
        source_kind: kind,
        name: values.name.trim(),
        enabled: values.enabled,
        source_config: sourceConfig(kind, values),
        grouping: grouping(kind, values),
        ...SINGLE_CHECK,
    } as PlatformAlertConfigurationCreateApi
}

/** An edit replaces every setting, so the ones this form does not show keep their stored values. */
export function buildEditBody(
    alert: PlatformAlertConfigurationApi,
    values: WarehouseAlertFormValues
): PlatformAlertConfigurationEditApi {
    const kind = alert.source_kind as WarehouseAlertKind
    const nextSourceConfig = sourceConfig(kind, values)
    // The backend checks the source config again only when it changes. Sending the stored one back when the
    // form leaves it alone keeps a rename or an on/off switch working on an alert that names a deleted source.
    const sourceConfigUnchanged = objectsEqual(nextSourceConfig, sourceConfig(kind, formValuesFromAlert(alert)))
    return {
        source_kind: kind,
        name: values.name.trim(),
        enabled: values.enabled,
        source_config: sourceConfigUnchanged ? alert.source_config : nextSourceConfig,
        grouping: grouping(kind, values, alert.grouping),
        schedule_restriction: alert.schedule_restriction,
        cooldown_minutes: alert.cooldown_minutes,
        ...SINGLE_CHECK,
    } as PlatformAlertConfigurationEditApi
}
