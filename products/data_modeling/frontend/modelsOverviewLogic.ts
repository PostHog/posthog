import { MakeLogicType, actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { DataModelingNode } from '~/types'

import {
    DataQualityOverviewCheckApi,
    DataQualitySubjectHealthApi,
} from 'products/data_quality/frontend/generated/api.schemas'
import {
    dataQualityOverviewLogic,
    subjectKeyOf,
} from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'
import { warehouseSavedQueriesRunCreate } from 'products/data_warehouse/frontend/generated/api'

import { nodeEndpointModel } from './endpointModelName'
import { BehindScheduleModel, MATERIALIZING_TYPES } from './freshness'
import type { ChecksHealth, RefreshSummary } from './healthyMessage'
import { lineageDataLogic } from './lineage/lineageDataLogic'
import { AttentionModel, modelsSceneLogic } from './modelsSceneLogic'
import {
    IssueKind,
    IssueStatus,
    REFRESH_FAILED_MESSAGE,
    REFRESH_STARTED_MESSAGE,
    SubjectSince,
    failingChecksStatus,
    materializationStatus,
    nextStepLabel,
    subjectDetail,
    subjectImpact,
    subjectName,
    subjectSince,
} from './overviewIssueCopy'
import { subjectHref } from './subjectHref'

const FAILING_CHECK_STATUSES = new Set(['failed', 'errored'])
const UNHEALTHY_SUBJECT_STATES = new Set(['failing', 'erroring', 'warn'])
const ALL = 'all'
const RUNNING = 'Running'
const REFRESH_POLL_INTERVAL_MS = 5000
const REFRESH_REQUEST_TIMEOUT_MS = 60_000

export type AttentionFilter = typeof ALL | IssueKind

export type MaterializationProblem =
    | { kind: 'suspended' | 'failed'; attention: AttentionModel }
    | { kind: 'behind'; behind: BehindScheduleModel }

export interface AttentionSubject {
    key: string
    node: DataModelingNode | null
    materialization: MaterializationProblem | null
    failingChecks: DataQualityOverviewCheckApi[]
}

export type AttentionNextStep =
    | { kind: 'refresh'; savedQueryId: string; refreshing: boolean }
    | { kind: 'link'; label: string; href: string }

export interface AttentionRow {
    key: string
    name: string
    href: string | null
    statuses: IssueStatus[]
    issueKinds: IssueKind[]
    detail: string | null
    impact: string | null
    since: SubjectSince | null
    nextStep: AttentionNextStep | null
}

export function problemNode(problem: MaterializationProblem): DataModelingNode {
    return problem.kind === 'behind' ? problem.behind.node : problem.attention.node
}

export function isFailingCheck(check: DataQualityOverviewCheckApi): boolean {
    return FAILING_CHECK_STATUSES.has(check.last_status ?? '')
}

function nodeSubjectKey(node: DataModelingNode): string {
    return node.saved_query_id ? `view-${node.saved_query_id}` : `node-${node.id}`
}

function checkSubjectKey(check: DataQualityOverviewCheckApi, node: DataModelingNode | null): string {
    return node ? nodeSubjectKey(node) : `${check.subject_type}-${check.subject_uuid ?? check.subject_name}`
}

function checkRollupKey(check: DataQualityOverviewCheckApi): string {
    return subjectKeyOf(check.subject_type, check.subject_uuid)
}

function isFailingSubject(health: DataQualitySubjectHealthApi): boolean {
    return health.checks_failing > 0 || UNHEALTHY_SUBJECT_STATES.has(health.health)
}

function groupAttentionSubjects(
    problems: MaterializationProblem[],
    failingChecks: DataQualityOverviewCheckApi[],
    nodes: DataModelingNode[]
): AttentionSubject[] {
    const nodesById = new Map(nodes.map((node) => [node.id, node]))
    const subjects = new Map<string, AttentionSubject>()
    for (const problem of problems) {
        const node = problemNode(problem)
        const key = nodeSubjectKey(node)
        if (!subjects.has(key)) {
            subjects.set(key, { key, node, materialization: problem, failingChecks: [] })
        }
    }
    for (const check of failingChecks) {
        const node = check.subject_node_id ? (nodesById.get(check.subject_node_id) ?? null) : null
        const key = checkSubjectKey(check, node)
        const subject = subjects.get(key) ?? { key, node, materialization: null, failingChecks: [] }
        subject.failingChecks.push(check)
        subjects.set(key, subject)
    }
    return [...subjects.values()]
}

export function subjectIssueKinds(subject: AttentionSubject): IssueKind[] {
    return [
        ...(subject.materialization ? [subject.materialization.kind] : []),
        ...(subject.failingChecks.length > 0 ? (['checks'] as const) : []),
    ]
}

function failingCheckCount(
    checks: DataQualityOverviewCheckApi[],
    healthBySubjectKey: Record<string, DataQualitySubjectHealthApi>
): number {
    const rollupKeys = new Set(checks.map(checkRollupKey))
    const rollupCount = [...rollupKeys].reduce(
        (total, key) => total + (healthBySubjectKey[key]?.checks_failing ?? 0),
        0
    )
    return Math.max(checks.length, rollupCount)
}

function subjectStatuses(
    subject: AttentionSubject,
    healthBySubjectKey: Record<string, DataQualitySubjectHealthApi>
): IssueStatus[] {
    const { materialization, failingChecks } = subject
    return [
        ...(materialization ? [materializationStatus(materialization)] : []),
        ...(failingChecks.length > 0
            ? [failingChecksStatus(failingChecks, failingCheckCount(failingChecks, healthBySubjectKey))]
            : []),
    ]
}

function refreshableSavedQueryId(subject: AttentionSubject): string | null {
    const { node, materialization } = subject
    const kind = materialization?.kind
    if (!node?.saved_query_id || nodeEndpointModel(node) || (kind !== 'failed' && kind !== 'behind')) {
        return null
    }
    return node.saved_query_id
}

function subjectNextStep(subject: AttentionSubject, refreshRequests: Record<string, number>): AttentionNextStep | null {
    const savedQueryId = refreshableSavedQueryId(subject)
    if (savedQueryId) {
        const refreshing = subject.node?.last_run_status === RUNNING || savedQueryId in refreshRequests
        return { kind: 'refresh', savedQueryId, refreshing }
    }
    const href = subjectHref(subject)
    return href ? { kind: 'link', label: nextStepLabel(subject), href } : null
}

export function buildAttentionRow(
    subject: AttentionSubject,
    healthBySubjectKey: Record<string, DataQualitySubjectHealthApi>,
    refreshRequests: Record<string, number>
): AttentionRow {
    return {
        key: subject.key,
        name: subjectName(subject),
        href: subjectHref(subject),
        statuses: subjectStatuses(subject, healthBySubjectKey),
        issueKinds: subjectIssueKinds(subject),
        detail: subjectDetail(subject),
        impact: subjectImpact(subject),
        since: subjectSince(subject),
        nextStep: subjectNextStep(subject, refreshRequests),
    }
}

function countByIssueKind(rows: AttentionRow[], unlistedFailingSubjectCount: number): Record<AttentionFilter, number> {
    const counts: Record<AttentionFilter, number> = {
        all: rows.length + unlistedFailingSubjectCount,
        suspended: 0,
        failed: 0,
        behind: 0,
        checks: unlistedFailingSubjectCount,
    }
    for (const kind of rows.flatMap((row) => row.issueKinds)) {
        counts[kind] += 1
    }
    return counts
}

function rollupChecksHealth(subjectHealth: DataQualitySubjectHealthApi[]): ChecksHealth {
    if (subjectHealth.every((health) => health.checks_total === 0)) {
        return 'none'
    }
    if (subjectHealth.some(isFailingSubject)) {
        return 'failing'
    }
    return subjectHealth.every((health) => health.health === 'healthy' || health.checks_total === 0)
        ? 'all-passed'
        : 'some-not-passed'
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface modelsOverviewLogicValues {
    checks: DataQualityOverviewCheckApi[] // dataQualityOverviewLogic
    healthBySubjectKey: {
        [k: string]: DataQualitySubjectHealthApi
    } // dataQualityOverviewLogic
    overviewError: string | null // dataQualityOverviewLogic
    snapshotLoaded: boolean // dataQualityOverviewLogic
    subjectHealth: DataQualitySubjectHealthApi[] // dataQualityOverviewLogic
    attentionModels: AttentionModel[] // modelsSceneLogic
    behindSchedule: BehindScheduleModel[] // modelsSceneLogic
    catalogRestructureEnabled: boolean // modelsSceneLogic
    modelsFailed: boolean // modelsSceneLogic
    modelsResolved: boolean // modelsSceneLogic
    noModelsYet: boolean // modelsSceneLogic
    nodes: DataModelingNode[] // modelsSceneLogic
    activeAttentionFilter: AttentionFilter
    attentionCounts: Record<AttentionFilter, number>
    attentionFilter: AttentionFilter
    attentionRows: AttentionRow[]
    attentionSubjects: AttentionSubject[]
    checksFirstLoading: boolean
    checksHealth: ChecksHealth
    checksKnown: boolean
    failingChecks: DataQualityOverviewCheckApi[]
    filteredAttentionRows: AttentionRow[]
    materializationProblems: MaterializationProblem[]
    modelsFirstLoading: boolean
    modelsKnown: boolean
    nothingToReport: boolean
    refreshRequests: Record<string, number>
    refreshSummary: RefreshSummary
    showFirstView: boolean
    unlistedFailingSubjectCount: number
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface modelsOverviewLogicActions {
    loadOverview: () => any // dataQualityOverviewLogic
    loadNodesSuccess: (
        nodes: DataModelingNode[],
        payload?: any
    ) => {
        nodes: DataModelingNode[]
        payload?: any
    } // lineageDataLogic
    loadDataWarehouseSavedQueries: () => any // modelsSceneLogic
    loadNodes: () => any // modelsSceneLogic
    clearRefreshRequests: (savedQueryIds: string[]) => {
        savedQueryIds: string[]
    }
    refreshRequestFailed: (savedQueryId: string) => {
        savedQueryId: string
    }
    requestRefresh: (savedQueryId: string) => {
        requestedAt: number
        savedQueryId: string
    }
    setAttentionFilter: (filter: AttentionFilter) => {
        filter: AttentionFilter
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface modelsOverviewLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        modelsKnown: (modelsResolved: boolean, modelsFailed: boolean) => boolean
        modelsFirstLoading: (modelsResolved: boolean, modelsFailed: boolean) => boolean
        checksKnown: (snapshotLoaded: boolean, overviewError: string | null) => boolean
        checksFirstLoading: (snapshotLoaded: boolean, overviewError: string | null) => boolean
        checksHealth: (subjectHealth: DataQualitySubjectHealthApi[]) => ChecksHealth
        materializationProblems: (
            attentionModels: AttentionModel[],
            behindSchedule: BehindScheduleModel[]
        ) => MaterializationProblem[]
        failingChecks: (checks: DataQualityOverviewCheckApi[]) => DataQualityOverviewCheckApi[]
        attentionSubjects: (
            materializationProblems: MaterializationProblem[],
            failingChecks: DataQualityOverviewCheckApi[],
            nodes: DataModelingNode[]
        ) => AttentionSubject[]
        attentionRows: (
            attentionSubjects: AttentionSubject[],
            healthBySubjectKey: {
                [k: string]: DataQualitySubjectHealthApi
            },
            refreshRequests: Record<string, number>
        ) => AttentionRow[]
        unlistedFailingSubjectCount: (
            subjectHealth: DataQualitySubjectHealthApi[],
            failingChecks: DataQualityOverviewCheckApi[]
        ) => number
        nothingToReport: (
            modelsKnown: boolean,
            checksKnown: boolean,
            attentionRows: AttentionRow[],
            unlistedFailingSubjectCount: number
        ) => boolean
        showFirstView: (nothingToReport: boolean, noModelsYet: boolean) => boolean
        refreshSummary: (nodes: DataModelingNode[]) => RefreshSummary
        attentionCounts: (
            attentionRows: AttentionRow[],
            unlistedFailingSubjectCount: number
        ) => Record<AttentionFilter, number>
        activeAttentionFilter: (
            attentionFilter: AttentionFilter,
            attentionCounts: Record<AttentionFilter, number>
        ) => AttentionFilter
        filteredAttentionRows: (attentionRows: AttentionRow[], activeAttentionFilter: AttentionFilter) => AttentionRow[]
    }
}

export type modelsOverviewLogicType = MakeLogicType<
    modelsOverviewLogicValues,
    modelsOverviewLogicActions,
    Record<string, any>,
    modelsOverviewLogicMeta
>

export const modelsOverviewLogic = kea<modelsOverviewLogicType>([
    path(['products', 'data_modeling', 'frontend', 'modelsOverviewLogic']),
    connect(() => ({
        values: [
            modelsSceneLogic,
            [
                'nodes',
                'attentionModels',
                'behindSchedule',
                'modelsResolved',
                'modelsFailed',
                'noModelsYet',
                'catalogRestructureEnabled',
            ],
            dataQualityOverviewLogic,
            ['checks', 'subjectHealth', 'healthBySubjectKey', 'snapshotLoaded', 'overviewError'],
        ],
        actions: [
            modelsSceneLogic,
            ['loadNodes', 'loadDataWarehouseSavedQueries'],
            dataQualityOverviewLogic,
            ['loadOverview'],
            lineageDataLogic,
            ['loadNodesSuccess'],
        ],
    })),
    actions({
        setAttentionFilter: (filter: AttentionFilter) => ({ filter }),
        requestRefresh: (savedQueryId: string) => ({ savedQueryId, requestedAt: Date.now() }),
        refreshRequestFailed: (savedQueryId: string) => ({ savedQueryId }),
        clearRefreshRequests: (savedQueryIds: string[]) => ({ savedQueryIds }),
    }),
    reducers({
        attentionFilter: [
            ALL as AttentionFilter,
            {
                setAttentionFilter: (_, { filter }) => filter,
            },
        ],
        refreshRequests: [
            {} as Record<string, number>,
            {
                requestRefresh: (state, { savedQueryId, requestedAt }) =>
                    savedQueryId in state ? state : { ...state, [savedQueryId]: requestedAt },
                refreshRequestFailed: (state, { savedQueryId }) => {
                    const { [savedQueryId]: _failed, ...rest } = state
                    return rest
                },
                clearRefreshRequests: (state, { savedQueryIds }) =>
                    Object.fromEntries(Object.entries(state).filter(([id]) => !savedQueryIds.includes(id))),
            },
        ],
    }),
    selectors({
        modelsKnown: [
            (s) => [s.modelsResolved, s.modelsFailed],
            (modelsResolved: boolean, modelsFailed: boolean): boolean => modelsResolved && !modelsFailed,
        ],
        modelsFirstLoading: [
            (s) => [s.modelsResolved, s.modelsFailed],
            (modelsResolved: boolean, modelsFailed: boolean): boolean => !modelsResolved && !modelsFailed,
        ],
        checksKnown: [
            (s) => [s.snapshotLoaded, s.overviewError],
            (snapshotLoaded: boolean, overviewError: string | null): boolean => snapshotLoaded && !overviewError,
        ],
        checksFirstLoading: [
            (s) => [s.snapshotLoaded, s.overviewError],
            (snapshotLoaded: boolean, overviewError: string | null): boolean => !snapshotLoaded && !overviewError,
        ],
        checksHealth: [
            (s) => [s.subjectHealth],
            (subjectHealth: DataQualitySubjectHealthApi[]): ChecksHealth => rollupChecksHealth(subjectHealth),
        ],
        materializationProblems: [
            (s) => [s.attentionModels, s.behindSchedule],
            (attentionModels: AttentionModel[], behindSchedule: BehindScheduleModel[]): MaterializationProblem[] => [
                ...attentionModels.map(
                    (attention): MaterializationProblem => ({
                        kind: attention.problem === 'Suspended' ? 'suspended' : 'failed',
                        attention,
                    })
                ),
                ...behindSchedule.map((behind): MaterializationProblem => ({ kind: 'behind', behind })),
            ],
        ],
        failingChecks: [
            (s) => [s.checks],
            (checks: DataQualityOverviewCheckApi[]): DataQualityOverviewCheckApi[] => checks.filter(isFailingCheck),
        ],
        attentionSubjects: [
            (s) => [s.materializationProblems, s.failingChecks, s.nodes],
            (
                materializationProblems: MaterializationProblem[],
                failingChecks: DataQualityOverviewCheckApi[],
                nodes: DataModelingNode[]
            ): AttentionSubject[] => groupAttentionSubjects(materializationProblems, failingChecks, nodes),
        ],
        attentionRows: [
            (s) => [s.attentionSubjects, s.healthBySubjectKey, s.refreshRequests],
            (
                attentionSubjects: AttentionSubject[],
                healthBySubjectKey: Record<string, DataQualitySubjectHealthApi>,
                refreshRequests: Record<string, number>
            ): AttentionRow[] =>
                attentionSubjects.map((subject) => buildAttentionRow(subject, healthBySubjectKey, refreshRequests)),
        ],
        unlistedFailingSubjectCount: [
            (s) => [s.subjectHealth, s.failingChecks],
            (subjectHealth: DataQualitySubjectHealthApi[], failingChecks: DataQualityOverviewCheckApi[]): number => {
                const listedKeys = new Set(failingChecks.map(checkRollupKey))
                return subjectHealth.filter(
                    (health) =>
                        isFailingSubject(health) &&
                        !listedKeys.has(subjectKeyOf(health.subject_type, health.subject_uuid))
                ).length
            },
        ],
        nothingToReport: [
            (s) => [s.modelsKnown, s.checksKnown, s.attentionRows, s.unlistedFailingSubjectCount],
            (
                modelsKnown: boolean,
                checksKnown: boolean,
                attentionRows: AttentionRow[],
                unlistedFailingSubjectCount: number
            ): boolean => modelsKnown && checksKnown && attentionRows.length === 0 && unlistedFailingSubjectCount === 0,
        ],
        showFirstView: [
            (s) => [s.nothingToReport, s.noModelsYet],
            (nothingToReport: boolean, noModelsYet: boolean): boolean => nothingToReport && noModelsYet,
        ],
        refreshSummary: [
            (s) => [s.nodes],
            (nodes: DataModelingNode[]): RefreshSummary => {
                const materialized = nodes.filter((node) => MATERIALIZING_TYPES.has(node.type))
                const runTimes = materialized.flatMap((node) => (node.last_run_at ? [node.last_run_at] : []))
                return { materializedCount: materialized.length, lastRefreshAt: runTimes.sort().at(-1) ?? null }
            },
        ],
        attentionCounts: [
            (s) => [s.attentionRows, s.unlistedFailingSubjectCount],
            (attentionRows: AttentionRow[], unlistedFailingSubjectCount: number): Record<AttentionFilter, number> =>
                countByIssueKind(attentionRows, unlistedFailingSubjectCount),
        ],
        activeAttentionFilter: [
            (s) => [s.attentionFilter, s.attentionCounts],
            (attentionFilter: AttentionFilter, attentionCounts: Record<AttentionFilter, number>): AttentionFilter =>
                attentionCounts[attentionFilter] > 0 ? attentionFilter : ALL,
        ],
        filteredAttentionRows: [
            (s) => [s.attentionRows, s.activeAttentionFilter],
            (attentionRows: AttentionRow[], activeAttentionFilter: AttentionFilter): AttentionRow[] =>
                activeAttentionFilter === ALL
                    ? attentionRows
                    : attentionRows.filter((row) => row.issueKinds.includes(activeAttentionFilter)),
        ],
    }),
    listeners(({ actions, values, cache, selectors }) => ({
        requestRefresh: async ({ savedQueryId }, _breakpoint, _action, previousState) => {
            if (savedQueryId in selectors.refreshRequests(previousState)) {
                return
            }
            try {
                await warehouseSavedQueriesRunCreate(String(getCurrentTeamId()), savedQueryId, {})
            } catch {
                actions.refreshRequestFailed(savedQueryId)
                lemonToast.error(REFRESH_FAILED_MESSAGE)
                return
            }
            lemonToast.success(REFRESH_STARTED_MESSAGE)
            actions.loadNodes()
            actions.loadDataWarehouseSavedQueries()
        },
        loadNodesSuccess: ({ nodes }) => {
            const runningSavedQueryIds = new Set(
                nodes.flatMap((node) =>
                    node.last_run_status === RUNNING && node.saved_query_id ? [node.saved_query_id] : []
                )
            )
            const now = Date.now()
            const settled = Object.entries(values.refreshRequests)
                .filter(
                    ([savedQueryId, requestedAt]) =>
                        runningSavedQueryIds.has(savedQueryId) || now - requestedAt > REFRESH_REQUEST_TIMEOUT_MS
                )
                .map(([savedQueryId]) => savedQueryId)
            if (settled.length > 0) {
                actions.clearRefreshRequests(settled)
            }
            const keepPolling =
                Object.keys(values.refreshRequests).length > 0 ||
                values.attentionRows.some((row) => row.nextStep?.kind === 'refresh' && row.nextStep.refreshing)
            if (!keepPolling) {
                cache.disposables.dispose('refreshPoll')
                return
            }
            cache.disposables.add(() => {
                const timeoutId = setTimeout(() => actions.loadNodes(), REFRESH_POLL_INTERVAL_MS)
                return () => clearTimeout(timeoutId)
            }, 'refreshPoll')
        },
    })),
])
