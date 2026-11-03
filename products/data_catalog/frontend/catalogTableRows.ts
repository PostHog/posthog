import { urls } from 'scenes/urls'

import type {
    DatabaseSchemaDataWarehouseTable,
    DatabaseSchemaTable,
    DatabaseSchemaViewTable,
} from '~/queries/schema/schema-general'
import type { DataModelingNode } from '~/types'

import type { DataQualitySubjectRef } from 'products/data_quality/frontend/checksApi'
import { SubjectTypeEnumApi } from 'products/data_quality/frontend/generated/api.schemas'
import type { SubjectGroup } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import type { CertificationTargetType } from './certificationsLogic'
import type { DataCatalogCertificationApi } from './generated/api.schemas'

export type TablesFilter = 'failing' | 'no_checks' | 'proposed' | 'certified' | 'deprecated' | 'all'

export const TABLES_FILTERS: TablesFilter[] = ['failing', 'no_checks', 'proposed', 'certified', 'deprecated', 'all']

export const TABLES_FILTER_PARAM = 'filter'
export const TABLES_SEARCH_PARAM = 'table'

export const POSTHOG_ORIGIN = 'PostHog'
export const VIEW_ORIGIN = 'Your view'
export const SELF_MANAGED_ORIGIN = 'Self-managed'

const UNLISTED_ORIGINS: Record<string, string> = {
    [SubjectTypeEnumApi.PosthogTable]: POSTHOG_ORIGIN,
    [SubjectTypeEnumApi.Table]: 'Source table',
    [SubjectTypeEnumApi.View]: VIEW_ORIGIN,
}

const FAILING_CHECK_STATUSES = ['failed', 'errored']

export interface CertificationTarget {
    targetType: CertificationTargetType
    targetId: string
}

export interface CatalogTableRow {
    key: string
    name: string
    origin: string
    subject: DataQualitySubjectRef | null
    checkGroup: SubjectGroup | null
    failingCheckCount: number
    certification: DataCatalogCertificationApi | null
    certificationTarget: CertificationTarget | null
    refreshedAt: string | null
    detailUrl: string | null
}

export interface CatalogTableSources {
    posthogTables: DatabaseSchemaTable[]
    dataWarehouseTables: DatabaseSchemaDataWarehouseTable[]
    views: DatabaseSchemaViewTable[]
    checkGroups: SubjectGroup[]
    certifications: DataCatalogCertificationApi[]
    nodes: DataModelingNode[]
    posthogTableSubjectIds: Record<string, string>
}

function certificationKey(certification: DataCatalogCertificationApi): string | null {
    if (certification.table) {
        return `${SubjectTypeEnumApi.Table}:${certification.table}`
    }
    if (certification.saved_query) {
        return `${SubjectTypeEnumApi.View}:${certification.saved_query}`
    }
    return null
}

function countFailingChecks(group: SubjectGroup | null): number {
    return group?.checks.filter((check) => FAILING_CHECK_STATUSES.includes(check.last_status ?? '')).length ?? 0
}

function sourceTableDetailUrl(table: DatabaseSchemaDataWarehouseTable): string {
    if (table.source && table.schema) {
        return urls.dataWarehouseSourceSchema(table.source.id, table.schema.id)
    }
    return urls.dataWarehouseSource(`self-managed-${table.id}`)
}

export function buildCatalogTableRows(sources: CatalogTableSources): CatalogTableRow[] {
    const groupsByKey = new Map(sources.checkGroups.map((group) => [group.subjectKey, group]))
    const certificationsByKey = new Map<string, DataCatalogCertificationApi>()
    for (const certification of sources.certifications) {
        const key = certificationKey(certification)
        if (key) {
            certificationsByKey.set(key, certification)
        }
    }
    const nodesBySavedQueryId = new Map(
        sources.nodes.filter((node) => node.saved_query_id).map((node) => [node.saved_query_id, node])
    )
    const posthogNodesByName = new Map(
        sources.nodes.filter((node) => node.origin === 'posthog').map((node) => [node.name, node])
    )
    const claimedGroupKeys = new Set<string>()
    const takeGroup = (key: string): SubjectGroup | null => {
        const group = groupsByKey.get(key) ?? null
        if (group) {
            claimedGroupKeys.add(key)
        }
        return group
    }
    const rowFor = (
        row: Omit<CatalogTableRow, 'failingCheckCount' | 'certification'>,
        certificationLookupKey: string | null
    ): CatalogTableRow => ({
        ...row,
        failingCheckCount: countFailingChecks(row.checkGroup),
        certification: certificationLookupKey ? (certificationsByKey.get(certificationLookupKey) ?? null) : null,
    })

    const posthogRows = sources.posthogTables.map((table) => {
        const subjectId = sources.posthogTableSubjectIds[table.name]
        const checkGroup = subjectId ? takeGroup(`${SubjectTypeEnumApi.PosthogTable}:${subjectId}`) : null
        const node = posthogNodesByName.get(table.name)
        return rowFor(
            {
                key: `posthog:${table.name}`,
                name: table.name,
                origin: POSTHOG_ORIGIN,
                subject: subjectId ? { subjectType: SubjectTypeEnumApi.PosthogTable, subjectId } : null,
                checkGroup,
                certificationTarget: null,
                refreshedAt: null,
                detailUrl: node ? urls.nodeDetail(node.id) : (checkGroup?.detailUrl ?? null),
            },
            null
        )
    })

    const sourceRows = sources.dataWarehouseTables.map((table) => {
        const key = `${SubjectTypeEnumApi.Table}:${table.id}`
        return rowFor(
            {
                key,
                name: table.name,
                origin: table.source?.source_type ?? SELF_MANAGED_ORIGIN,
                subject: { subjectType: SubjectTypeEnumApi.Table, subjectId: table.id },
                checkGroup: takeGroup(key),
                certificationTarget: { targetType: 'table', targetId: table.id },
                refreshedAt: table.schema?.last_synced_at ?? table.source?.last_synced_at ?? null,
                detailUrl: sourceTableDetailUrl(table),
            },
            key
        )
    })

    const viewRows = sources.views.map((view) => {
        const key = `${SubjectTypeEnumApi.View}:${view.id}`
        const node = nodesBySavedQueryId.get(view.id)
        const checkGroup = takeGroup(key)
        return rowFor(
            {
                key,
                name: view.name,
                origin: VIEW_ORIGIN,
                subject: { subjectType: SubjectTypeEnumApi.View, subjectId: view.id },
                checkGroup,
                certificationTarget: { targetType: 'view', targetId: view.id },
                refreshedAt: node?.last_run_at ?? null,
                detailUrl: node ? urls.nodeDetail(node.id) : (checkGroup?.detailUrl ?? null),
            },
            key
        )
    })

    const unlistedRows = sources.checkGroups
        .filter((group) => group.subjectType !== SubjectTypeEnumApi.Metric && !claimedGroupKeys.has(group.subjectKey))
        .map((group) =>
            rowFor(
                {
                    key: group.subjectKey,
                    name: group.subjectName,
                    origin: UNLISTED_ORIGINS[group.subjectType] ?? group.subjectType,
                    subject: group.subjectUuid
                        ? { subjectType: group.subjectType, subjectId: group.subjectUuid }
                        : null,
                    checkGroup: group,
                    certificationTarget: null,
                    refreshedAt: null,
                    detailUrl: group.detailUrl,
                },
                null
            )
        )

    return [...posthogRows, ...sourceRows, ...viewRows, ...unlistedRows].sort(
        (left, right) =>
            Number(right.failingCheckCount > 0) - Number(left.failingCheckCount > 0) ||
            left.name.localeCompare(right.name)
    )
}

export function rowMatchesFilter(row: CatalogTableRow, filter: TablesFilter): boolean {
    switch (filter) {
        case 'failing':
            return row.failingCheckCount > 0
        case 'no_checks':
            return !row.checkGroup
        case 'all':
            return true
        default:
            return row.certification?.status === filter
    }
}

export function rowMatchesSearch(row: CatalogTableRow, search: string): boolean {
    const needle = search.trim().toLowerCase()
    return !needle || row.name.toLowerCase().includes(needle) || row.origin.toLowerCase().includes(needle)
}
