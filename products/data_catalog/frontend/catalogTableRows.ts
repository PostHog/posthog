import { pluralize } from 'lib/utils/strings'
import type { DataWarehouseSavedQuerySummary } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { urls } from 'scenes/urls'

import {
    DataWarehouseSavedQueryOrigin,
    type DatabaseSchemaDataWarehouseTable,
    type DatabaseSchemaManagedViewTable,
    type DatabaseSchemaTable,
    type DatabaseSchemaViewTable,
} from '~/queries/schema/schema-general'
import type { DataModelingNode } from '~/types'

import {
    AttentionSubject,
    MaterializationProblem,
    isFailingCheck,
    problemNode,
    subjectIssueKinds,
} from 'products/data_modeling/frontend/modelsOverviewLogic'
import { ISSUE_KIND_ORDER, type IssueKind } from 'products/data_modeling/frontend/overviewIssueCopy'
import type { DataQualitySubjectRef } from 'products/data_quality/frontend/checksApi'
import {
    type DataQualitySubjectHealthApi,
    SubjectTypeEnumApi,
} from 'products/data_quality/frontend/generated/api.schemas'
import { type SubjectGroup, subjectKeyOf } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { ColumnSort, SortValueGetters, sortByColumn } from './catalogSort'
import type { CertificationTargetType } from './certificationsLogic'
import type { DataCatalogCertificationApi } from './generated/api.schemas'

export type TableKind = 'posthog' | 'source' | 'self_managed' | 'view' | 'materialized_view'
export type TableScope = 'all' | 'attention'
export type TrustFilter = 'any' | 'certified' | 'proposed' | 'deprecated' | 'none'
export type ChecksFilter = 'any' | 'with' | 'without'

export const CHECKS_FILTER_OPTIONS: { value: ChecksFilter; label: string }[] = [
    { value: 'any', label: 'Any' },
    { value: 'with', label: 'With checks' },
    { value: 'without', label: 'Without checks' },
]

export interface TablesFilters {
    kind: TableKind | 'any'
    problem: IssueKind | 'any'
    trust: TrustFilter
    checks: ChecksFilter
}

export const DEFAULT_TABLES_FILTERS: TablesFilters = { kind: 'any', problem: 'any', trust: 'any', checks: 'any' }

export const TABLES_FILTER_PARAM = 'filter'
export const TABLES_SEARCH_PARAM = 'table'
export const PROPOSED_TABLES_FILTER = 'proposed'

export const KIND_LABELS: Record<TableKind, string> = {
    posthog: 'PostHog',
    source: 'Source table',
    self_managed: 'Self-managed',
    view: 'View',
    materialized_view: 'Materialized view',
}

const MANAGED_VIEW_ORIGIN = 'Managed view'

const UNLISTED_KINDS: Partial<Record<string, TableKind>> = {
    [SubjectTypeEnumApi.PosthogTable]: 'posthog',
    [SubjectTypeEnumApi.Table]: 'source',
    [SubjectTypeEnumApi.View]: 'view',
}

export interface CertificationTarget {
    targetType: CertificationTargetType
    targetId: string
}

export interface CheckCounts {
    total: number
    failing: number
}

export interface CatalogTableRow {
    key: string
    name: string
    kind: TableKind
    subtitle: string
    subject: DataQualitySubjectRef | null
    checkGroup: SubjectGroup | null
    checkCounts: CheckCounts
    health: AttentionSubject
    problems: IssueKind[]
    savedQuery: DataWarehouseSavedQuerySummary | null
    certification: DataCatalogCertificationApi | null
    certificationTarget: CertificationTarget | null
    refreshedAt: string | null
    detailUrl: string | null
}

export interface CatalogTableSources {
    posthogTables: DatabaseSchemaTable[]
    dataWarehouseTables: DatabaseSchemaDataWarehouseTable[]
    views: DatabaseSchemaViewTable[]
    managedViews: DatabaseSchemaManagedViewTable[]
    savedQueries: DataWarehouseSavedQuerySummary[]
    checkGroups: SubjectGroup[]
    healthBySubjectKey: Record<string, DataQualitySubjectHealthApi>
    certifications: DataCatalogCertificationApi[]
    nodes: DataModelingNode[]
    materializationProblems: MaterializationProblem[]
    posthogTableSubjectIds: Record<string, string>
}

type RowBase = Omit<CatalogTableRow, 'health' | 'problems' | 'certification' | 'subtitle' | 'checkCounts'> & {
    origin: string
    node: DataModelingNode | null
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

function sourceTableDetailUrl(table: DatabaseSchemaDataWarehouseTable): string {
    if (table.source && table.schema) {
        return urls.dataWarehouseSourceSchema(table.source.id, table.schema.id)
    }
    return urls.dataWarehouseSource(`self-managed-${table.id}`)
}

function subtitleFor(origin: string, node: DataModelingNode | null): string {
    const downstreamCount = node?.downstream_count ?? 0
    return downstreamCount > 0 ? `${origin} · feeds ${pluralize(downstreamCount, 'model')}` : origin
}

function attentionRank(row: CatalogTableRow): number {
    const [firstProblem] = row.problems
    return firstProblem ? ISSUE_KIND_ORDER.indexOf(firstProblem) : ISSUE_KIND_ORDER.length
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
    const savedQueriesById = new Map(sources.savedQueries.map((savedQuery) => [savedQuery.id, savedQuery]))
    const problemsByNodeId = new Map(
        sources.materializationProblems.map((problem) => [problemNode(problem).id, problem])
    )
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
    const rowFor = ({ origin, node, ...row }: RowBase, certificationLookupKey: string | null): CatalogTableRow => {
        const failingChecks = row.checkGroup?.checks.filter(isFailingCheck) ?? []
        const health: AttentionSubject = {
            key: row.key,
            node,
            materialization: node ? (problemsByNodeId.get(node.id) ?? null) : null,
            failingChecks,
        }
        const subjectHealth = row.subject
            ? sources.healthBySubjectKey[subjectKeyOf(row.subject.subjectType, row.subject.subjectId)]
            : undefined
        return {
            ...row,
            subtitle: subtitleFor(origin, node),
            checkCounts: rolledUpCheckCounts(subjectHealth, row.checkGroup),
            health,
            problems: subjectIssueKinds(health),
            certification: certificationLookupKey ? (certificationsByKey.get(certificationLookupKey) ?? null) : null,
        }
    }

    const posthogGroupsByName = new Map(
        sources.checkGroups
            .filter((group) => group.subjectType === SubjectTypeEnumApi.PosthogTable)
            .map((group) => [group.subjectName, group])
    )

    const posthogRows = sources.posthogTables.map((table) => {
        const groupByName = posthogGroupsByName.get(table.name)
        const subjectId = sources.posthogTableSubjectIds[table.name] ?? groupByName?.subjectUuid
        const checkGroup = subjectId ? takeGroup(`${SubjectTypeEnumApi.PosthogTable}:${subjectId}`) : null
        const node = posthogNodesByName.get(table.name) ?? null
        return rowFor(
            {
                key: `posthog:${table.name}`,
                name: table.name,
                kind: 'posthog',
                origin: KIND_LABELS.posthog,
                node,
                subject: subjectId ? { subjectType: SubjectTypeEnumApi.PosthogTable, subjectId } : null,
                checkGroup,
                savedQuery: null,
                certificationTarget: null,
                refreshedAt: null,
                detailUrl: node ? urls.nodeDetail(node.id) : (checkGroup?.detailUrl ?? null),
            },
            null
        )
    })

    const sourceRows = sources.dataWarehouseTables.map((table) => {
        const key = `${SubjectTypeEnumApi.Table}:${table.id}`
        const kind: TableKind = table.source ? 'source' : 'self_managed'
        return rowFor(
            {
                key,
                name: table.name,
                kind,
                origin: table.source?.source_type ?? KIND_LABELS.self_managed,
                node: null,
                subject: { subjectType: SubjectTypeEnumApi.Table, subjectId: table.id },
                checkGroup: takeGroup(key),
                savedQuery: null,
                certificationTarget: { targetType: 'table', targetId: table.id },
                refreshedAt: table.schema?.last_synced_at ?? table.source?.last_synced_at ?? null,
                detailUrl: sourceTableDetailUrl(table),
            },
            key
        )
    })

    const viewRows = sources.views
        .filter((view) => savedQueriesById.get(view.id)?.origin !== DataWarehouseSavedQueryOrigin.ENDPOINT)
        .map((view) => {
            const key = `${SubjectTypeEnumApi.View}:${view.id}`
            const node = nodesBySavedQueryId.get(view.id) ?? null
            const savedQuery = savedQueriesById.get(view.id) ?? null
            const kind: TableKind = savedQuery?.is_materialized ? 'materialized_view' : 'view'
            const checkGroup = takeGroup(key)
            return rowFor(
                {
                    key,
                    name: view.name,
                    kind,
                    origin: KIND_LABELS[kind],
                    node,
                    subject: { subjectType: SubjectTypeEnumApi.View, subjectId: view.id },
                    checkGroup,
                    savedQuery,
                    certificationTarget: { targetType: 'view', targetId: view.id },
                    refreshedAt: node?.last_run_at ?? savedQuery?.last_run_at ?? null,
                    detailUrl: node ? urls.nodeDetail(node.id) : (checkGroup?.detailUrl ?? null),
                },
                key
            )
        })

    const managedViewRows = sources.managedViews.map((view) =>
        rowFor(
            {
                key: `managed_view:${view.id}`,
                name: view.name,
                kind: 'view',
                origin: MANAGED_VIEW_ORIGIN,
                node: null,
                subject: null,
                checkGroup: null,
                savedQuery: null,
                certificationTarget: null,
                refreshedAt: null,
                detailUrl: null,
            },
            null
        )
    )

    const isEndpointGroup = (group: SubjectGroup): boolean =>
        group.subjectType === SubjectTypeEnumApi.View &&
        savedQueriesById.get(group.subjectUuid)?.origin === DataWarehouseSavedQueryOrigin.ENDPOINT

    const unlistedRows = sources.checkGroups.flatMap((group) => {
        const kind = UNLISTED_KINDS[group.subjectType]
        if (!kind || claimedGroupKeys.has(group.subjectKey) || isEndpointGroup(group)) {
            return []
        }
        return [
            rowFor(
                {
                    key: group.subjectKey,
                    name: group.subjectName,
                    kind,
                    origin: KIND_LABELS[kind],
                    node: null,
                    subject: group.subjectUuid
                        ? { subjectType: group.subjectType, subjectId: group.subjectUuid }
                        : null,
                    checkGroup: group,
                    savedQuery: null,
                    certificationTarget: null,
                    refreshedAt: null,
                    detailUrl: group.detailUrl,
                },
                null
            ),
        ]
    })

    return [...posthogRows, ...sourceRows, ...viewRows, ...managedViewRows, ...unlistedRows].sort(
        (left, right) => attentionRank(left) - attentionRank(right) || left.name.localeCompare(right.name)
    )
}

export function rowNeedsAttention(row: CatalogTableRow): boolean {
    return row.problems.length > 0
}

function matchesTrust(row: CatalogTableRow, trust: TrustFilter): boolean {
    if (trust === 'any') {
        return true
    }
    if (trust === 'none') {
        return !row.certification
    }
    return row.certification?.status === trust
}

export function matchesChecksFilter(hasChecks: boolean, checks: ChecksFilter): boolean {
    return checks === 'any' || (checks === 'with') === hasChecks
}

export function rowMatchesFilters(row: CatalogTableRow, filters: TablesFilters): boolean {
    return (
        (filters.kind === 'any' || row.kind === filters.kind) &&
        (filters.problem === 'any' || row.problems.includes(filters.problem)) &&
        matchesTrust(row, filters.trust) &&
        matchesChecksFilter(row.checkCounts.total > 0, filters.checks)
    )
}

export function rowMatchesSearch(row: CatalogTableRow, search: string): boolean {
    const needle = search.trim().toLowerCase()
    return !needle || row.name.toLowerCase().includes(needle) || row.subtitle.toLowerCase().includes(needle)
}

export type TablesSortColumn = 'name' | 'status' | 'checks' | 'trust' | 'refresh'

export type TablesSort = ColumnSort<TablesSortColumn>

const TRUST_RANK: Record<string, number> = { certified: 0, proposed: 1, deprecated: 2 }

export function checkGroupCounts(group: SubjectGroup | null | undefined): CheckCounts | null {
    const checks = group?.checks ?? []
    if (checks.length === 0) {
        return null
    }
    return { total: checks.length, failing: checks.filter((check) => check.last_status !== 'passed').length }
}

export function rolledUpCheckCounts(
    subjectHealth: DataQualitySubjectHealthApi | undefined,
    group: SubjectGroup | null | undefined
): CheckCounts {
    const checks = group?.checks ?? []
    return {
        total: Math.max(subjectHealth?.checks_total ?? 0, checks.length),
        failing: Math.max(subjectHealth?.checks_failing ?? 0, checks.filter(isFailingCheck).length),
    }
}

export function displayedCheckCounts(
    group: SubjectGroup | null | undefined,
    rolledUp: CheckCounts
): CheckCounts | null {
    return checkGroupCounts(group) ?? (rolledUp.total > 0 ? rolledUp : null)
}

export function passingChecks(row: CatalogTableRow): CheckCounts | null {
    return displayedCheckCounts(row.checkGroup, row.checkCounts)
}

export function passingShare(counts: CheckCounts | null): number | null {
    return counts ? (counts.total - counts.failing) / counts.total : null
}

const SORT_VALUES: SortValueGetters<CatalogTableRow, TablesSortColumn> = {
    name: (row) => row.name,
    status: attentionRank,
    checks: (row) => passingShare(passingChecks(row)),
    trust: (row) => (row.certification ? (TRUST_RANK[row.certification.status] ?? null) : null),
    refresh: (row) => row.refreshedAt,
}

export function sortCatalogTableRows(rows: CatalogTableRow[], sort: TablesSort | null): CatalogTableRow[] {
    return sortByColumn(rows, sort, SORT_VALUES, (row) => row.name)
}

export type ProposalDecision = 'accept' | 'reject'
export type ReviewSource = 'inline' | 'menu' | 'bulk'

export function hasPendingProposal(row: CatalogTableRow): boolean {
    return row.certification?.status === 'proposed'
}

export function proposalAcceptsAsDeprecation(certification: DataCatalogCertificationApi): boolean {
    return certification.proposed_status === 'deprecated'
}

export function canCertify(row: CatalogTableRow): boolean {
    return !!row.certificationTarget && row.certification?.status !== 'certified'
}

export function rowIsExpandable(row: CatalogTableRow): boolean {
    return !!row.checkGroup
}
