import {
    LogicWrapper,
    MakeLogicType,
    actions,
    afterMount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { ApiConfig } from 'lib/api'
import { chunk } from 'lib/utils/arrays'

import { aiObservabilityTracesList, aiObservabilityTracesTurnsCreate } from '../../generated/api'
import {
    AiObservabilityTracesListOrder,
    type AiObservabilityTracesListParams,
    type TraceListApi,
    type TraceListItemApi,
    type TraceTurnApi,
    type TraceTurnListApi,
} from '../../generated/api.schemas'
import { readAbortablePage } from '../lists/cursorPaging'
import { CellLoads, TraceCellLoad, withFailed, withLoaded, withRequested } from '../shared/cellLoads'
import { createCellReader } from '../shared/cellReader'
import { noEntries } from '../shared/readOrFailure'
import type { TraceDrawerListId } from '../trace/traceDrawerLists'
import { traceDrawerLogic } from '../trace/traceDrawerLogic'
import type { TraceListRow } from '../trace/traceListRows'
import type { ConversationState, ConversationTurn, NodeSideContent } from '../trace/types'
import { sessionsTracking } from './sessionsTracking'

export const SESSION_TURNS_PAGE_SIZE = 20
export const SESSION_TURNS_LIST: TraceDrawerListId = 'session-turns'

export interface SessionConversationLogicProps {
    sessionId: string
    firstSeen: string
    lastSeen: string
    /** A turn to open the conversation on, instead of the first. */
    aroundTraceId: string | null
}

export type ConversationPageDirection = 'first' | 'older' | 'newer'

export interface ConversationPageRequest {
    direction: ConversationPageDirection
    params: AiObservabilityTracesListParams
}

/** Where the loaded turns end on one side: `waiting` has more to read once the read in flight lands. */
export type ConversationEdge = 'more' | 'waiting' | 'loading' | 'failed' | 'end'

const EMPTY_SIDE: NodeSideContent = { kind: 'messages', messages: [] }
const FIRST_PAGE_ERROR = "Couldn't load this session."

// A session reads on its own: list filters sent with it are refused, and its window is its own first and last activity.
function sessionPageParams({
    sessionId,
    firstSeen,
    lastSeen,
}: SessionConversationLogicProps): AiObservabilityTracesListParams {
    return {
        session_id: sessionId,
        order: AiObservabilityTracesListOrder.OldestFirst,
        date_from: firstSeen,
        date_to: lastSeen,
        limit: SESSION_TURNS_PAGE_SIZE,
    }
}

function mergedItems(
    items: ReadonlyMap<string, TraceListItemApi>,
    page: TraceListItemApi[],
    direction: ConversationPageDirection
): ReadonlyMap<string, TraceListItemApi> {
    const entries = page.map((item): [string, TraceListItemApi] => [item.id, item])
    if (direction === 'first') {
        return new Map(entries)
    }
    return direction === 'older' ? new Map([...entries, ...items]) : new Map([...items, ...entries])
}

function emptyTurn(traceId: string): TraceTurnApi {
    return { traceId, input: null, output: null, inputMissingReason: null, outputMissingReason: null }
}

async function readTurnsOf(projectId: string, rows: TraceListItemApi[]): Promise<TraceTurnListApi> {
    const createdAts = rows.map((row) => row.createdAt).sort((a, b) => Date.parse(a) - Date.parse(b))
    const { items } = await aiObservabilityTracesTurnsCreate(projectId, {
        trace_ids: rows.map((row) => row.id),
        earliest_created_at: createdAts[0],
        latest_created_at: createdAts[createdAts.length - 1],
    })
    // The read leaves out a trace with no events. Its turn has nothing to show, and must not stay loading.
    const found = new Map(items.map((turn) => [turn.traceId, turn]))
    return { items: rows.map((row) => found.get(row.id) ?? emptyTurn(row.id)) }
}

function toTurn(item: TraceListItemApi, sides: TraceCellLoad<TraceTurnApi> | undefined): ConversationTurn {
    const turn: ConversationTurn = {
        id: item.id,
        timestamp: item.createdAt,
        waitMs: item.totals.latencyMs,
        input: EMPTY_SIDE,
        output: EMPTY_SIDE,
        error: item.firstError,
    }
    if (sides?.status !== 'ready') {
        return { ...turn, pending: sides?.status === 'error' ? 'error' : 'loading' }
    }
    const { input, output, inputMissingReason, outputMissingReason } = sides.value
    return {
        ...turn,
        input: input ?? EMPTY_SIDE,
        output: output ?? EMPTY_SIDE,
        ...((inputMissingReason || outputMissingReason) && {
            missingReasons: { input: inputMissingReason, output: outputMissingReason },
        }),
    }
}

function toRow(item: TraceListItemApi): TraceListRow {
    return {
        traceId: item.id,
        timestamp: item.createdAt,
        stepId: null,
        overview: item,
        defaultStepId: item.defaultNodeId ?? undefined,
    }
}

function edgeOf(
    direction: ConversationPageDirection,
    cursor: string | null,
    pageRequest: ConversationPageRequest | null,
    pageLoading: boolean,
    pageFailed: boolean
): ConversationEdge {
    if (pageRequest?.direction === direction && (pageLoading || pageFailed)) {
        return pageLoading ? 'loading' : 'failed'
    }
    if (!cursor) {
        return 'end'
    }
    return pageLoading ? 'waiting' : 'more'
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface sessionConversationLogicValues {
    openTraceId: string | null // traceDrawerLogic
    firstPageLoaded: boolean
    items: ReadonlyMap<string, TraceListItemApi>
    newerCursor: string | null
    newerEdge: ConversationEdge
    olderCursor: string | null
    olderEdge: ConversationEdge
    page: TraceListApi | null
    pageFailed: boolean
    pageLoading: boolean
    pageRequest: ConversationPageRequest | null
    rows: TraceListRow[]
    turnSides: CellLoads<TraceTurnApi>
    turns: ConversationState
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface sessionConversationLogicActions {
    openRow: (row: TraceListRow) => {
        row: TraceListRow
    } // traceDrawerLogic
    stepTo: (direction: import('../trace/traceDrawerLogic').TraceStepDirection) => {
        direction: import('../trace/traceDrawerLogic').TraceStepDirection
    } // traceDrawerLogic
    loadConversationPage: ({ params }: ConversationPageRequest) => ConversationPageRequest
    loadConversationPageFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadConversationPageSuccess: (
        page: TraceListApi,
        payload?: ConversationPageRequest
    ) => {
        page: TraceListApi
        payload?: ConversationPageRequest
    }
    loadNewer: () => {
        value: true
    }
    loadOlder: () => {
        value: true
    }
    openTurn: (
        turnId: string,
        stepId: string
    ) => {
        stepId: string
        turnId: string
    }
    reload: () => {
        value: true
    }
    retryTurns: () => {
        value: true
    }
    turnsFailed: (traceIds: string[]) => {
        traceIds: string[]
    }
    turnsLoaded: (turns: TraceTurnApi[]) => {
        turns: TraceTurnApi[]
    }
    turnsRequested: (traceIds: string[]) => {
        traceIds: string[]
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface sessionConversationLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        turns: (
            items: ReadonlyMap<string, TraceListItemApi>,
            turnSides: CellLoads<TraceTurnApi>,
            firstPageLoaded: boolean,
            pageFailed: boolean,
            openTraceId: string | null
        ) => ConversationState
        rows: (items: ReadonlyMap<string, TraceListItemApi>) => TraceListRow[]
        olderEdge: (
            olderCursor: string | null,
            pageRequest: ConversationPageRequest | null,
            pageLoading: boolean,
            pageFailed: boolean
        ) => ConversationEdge
        newerEdge: (
            newerCursor: string | null,
            pageRequest: ConversationPageRequest | null,
            pageLoading: boolean,
            pageFailed: boolean
        ) => ConversationEdge
    }
}

export type sessionConversationLogicType = MakeLogicType<
    sessionConversationLogicValues,
    sessionConversationLogicActions,
    SessionConversationLogicProps,
    sessionConversationLogicMeta
>

export const sessionConversationLogic: LogicWrapper<sessionConversationLogicType> = kea<sessionConversationLogicType>([
    props({} as SessionConversationLogicProps),
    key((props) => props.sessionId),
    path((key) => [
        'products',
        'ai_observability',
        'frontend',
        'redesign',
        'sessions',
        'sessionConversationLogic',
        key,
    ]),
    connect(() => ({
        values: [traceDrawerLogic({ listId: SESSION_TURNS_LIST }), ['openTraceId']],
        actions: [traceDrawerLogic({ listId: SESSION_TURNS_LIST }), ['openRow', 'stepTo']],
    })),
    actions({
        reload: true,
        loadOlder: true,
        loadNewer: true,
        retryTurns: true,
        openTurn: (turnId: string, stepId: string) => ({ turnId, stepId }),
        turnsRequested: (traceIds: string[]) => ({ traceIds }),
        turnsFailed: (traceIds: string[]) => ({ traceIds }),
        turnsLoaded: (turns: TraceTurnApi[]) => ({ turns }),
    }),
    loaders(({ cache }) => ({
        page: [
            null as TraceListApi | null,
            {
                loadConversationPage: async (
                    { params }: ConversationPageRequest,
                    breakpoint
                ): Promise<TraceListApi> => {
                    cache.pageRequestedAt = performance.now()
                    return readAbortablePage(
                        cache,
                        (signal) =>
                            aiObservabilityTracesList(String(ApiConfig.getCurrentProjectId()), params, { signal }),
                        breakpoint
                    )
                },
            },
        ],
    })),
    reducers({
        items: [
            noEntries<TraceListItemApi>(),
            {
                loadConversationPageSuccess: (items, { page, payload }) =>
                    payload ? mergedItems(items, page.items, payload.direction) : items,
            },
        ],
        olderCursor: [
            null as string | null,
            {
                loadConversationPageSuccess: (cursor, { page, payload }) =>
                    payload?.direction === 'newer' ? cursor : page.previousCursor,
            },
        ],
        newerCursor: [
            null as string | null,
            {
                loadConversationPageSuccess: (cursor, { page, payload }) =>
                    payload?.direction === 'older' ? cursor : page.nextCursor,
            },
        ],
        firstPageLoaded: [
            false,
            {
                loadConversationPageSuccess: (loaded, { payload }) => loaded || payload?.direction === 'first',
            },
        ],
        pageRequest: [
            null as ConversationPageRequest | null,
            {
                loadConversationPage: (_, request) => request,
            },
        ],
        pageFailed: [
            false,
            {
                loadConversationPage: () => false,
                loadConversationPageFailure: () => true,
            },
        ],
        turnSides: [
            noEntries<TraceCellLoad<TraceTurnApi>>() as CellLoads<TraceTurnApi>,
            {
                turnsRequested: (state, { traceIds }) => withRequested(state, traceIds),
                turnsFailed: (state, { traceIds }) => withFailed(state, traceIds),
                turnsLoaded: (state, { turns }) =>
                    withLoaded(
                        state,
                        turns.map((turn) => [turn.traceId, turn])
                    ),
            },
        ],
    }),
    selectors({
        turns: [
            (s) => [s.items, s.turnSides, s.firstPageLoaded, s.pageFailed, s.openTraceId],
            (
                items: ReadonlyMap<string, TraceListItemApi>,
                turnSides: CellLoads<TraceTurnApi>,
                firstPageLoaded: boolean,
                pageFailed: boolean,
                openTraceId: string | null
            ): ConversationState => {
                if (!firstPageLoaded) {
                    return pageFailed ? { status: 'error', message: FIRST_PAGE_ERROR } : { status: 'loading' }
                }
                return {
                    status: 'ready',
                    turns: [...items.values()].map((item) => toTurn(item, turnSides.get(item.id))),
                    activeTurnId: openTraceId,
                }
            },
        ],
        rows: [
            (s) => [s.items],
            (items: ReadonlyMap<string, TraceListItemApi>): TraceListRow[] => [...items.values()].map(toRow),
        ],
        olderEdge: [
            (s) => [s.olderCursor, s.pageRequest, s.pageLoading, s.pageFailed],
            (
                cursor: string | null,
                pageRequest: ConversationPageRequest | null,
                pageLoading: boolean,
                pageFailed: boolean
            ): ConversationEdge => edgeOf('older', cursor, pageRequest, pageLoading, pageFailed),
        ],
        newerEdge: [
            (s) => [s.newerCursor, s.pageRequest, s.pageLoading, s.pageFailed],
            (
                cursor: string | null,
                pageRequest: ConversationPageRequest | null,
                pageLoading: boolean,
                pageFailed: boolean
            ): ConversationEdge => edgeOf('newer', cursor, pageRequest, pageLoading, pageFailed),
        ],
    }),
    listeners(({ actions, values, props, cache }) => {
        const readCells = createCellReader<TraceListItemApi, 'turns'>({
            cache,
            idOf: (item) => item.id,
            requested: (_, traceIds) => actions.turnsRequested(traceIds),
            failed: (_, traceIds) => actions.turnsFailed(traceIds),
        })

        const readTurns = async (traceIds: string[]): Promise<void> => {
            const projectId = String(ApiConfig.getCurrentProjectId())
            const rows = traceIds
                .map((traceId) => values.items.get(traceId))
                .filter((item): item is TraceListItemApi => item !== undefined)
            await Promise.all(
                chunk(rows, SESSION_TURNS_PAGE_SIZE).map((pageRows) =>
                    readCells(
                        'turns',
                        pageRows,
                        (requested) => readTurnsOf(projectId, requested),
                        (turns) => actions.turnsLoaded(turns)
                    )
                )
            )
        }

        const loadPage = (
            direction: ConversationPageDirection,
            cursor: Partial<AiObservabilityTracesListParams>
        ): void => {
            actions.loadConversationPage({ direction, params: { ...sessionPageParams(props), ...cursor } })
        }

        // The drawer steps through the loaded turns only, so the last one open brings in the page after it. Earlier
        // turns load only on a step up: they go above the reader, and would move the turn they opened.
        const loadPastOpenTurn = (): void => {
            const lastRow = values.rows[values.rows.length - 1]
            if (lastRow && lastRow.traceId === values.openTraceId && values.newerEdge === 'more') {
                actions.loadNewer()
            }
        }

        return {
            [router.actionTypes.locationChanged]: loadPastOpenTurn,
            stepTo: ({ direction }) => {
                const firstRow = values.rows[0]
                if (
                    direction === 'previous' &&
                    firstRow?.traceId === values.openTraceId &&
                    values.olderEdge === 'more'
                ) {
                    cache.openBeforeTraceId = firstRow.traceId
                    actions.loadOlder()
                }
            },
            loadConversationPageFailure: () => {
                cache.openBeforeTraceId = null
            },
            reload: () => loadPage('first', props.aroundTraceId ? { around: props.aroundTraceId } : {}),
            loadOlder: () => {
                if (values.olderCursor && !values.pageLoading) {
                    loadPage('older', { before_cursor: values.olderCursor })
                }
            },
            loadNewer: () => {
                if (values.newerCursor && !values.pageLoading) {
                    loadPage('newer', { cursor: values.newerCursor })
                }
            },
            loadConversationPageSuccess: async ({ page, payload }) => {
                if (payload?.direction === 'older' && cache.openBeforeTraceId) {
                    const index = values.rows.findIndex((row) => row.traceId === cache.openBeforeTraceId)
                    cache.openBeforeTraceId = null
                    if (index > 0) {
                        actions.openRow(values.rows[index - 1])
                    }
                }
                loadPastOpenTurn()
                const rowsWaitMs = Math.round(performance.now() - cache.pageRequestedAt)
                const traceIds = page.items.map((item) => item.id)
                const turnsRequestedAt = performance.now()
                await readTurns(traceIds)
                if (cache.disposables.isDisposed) {
                    return
                }
                const turnsLoaded = traceIds.every((traceId) => values.turnSides.get(traceId)?.status === 'ready')
                if (payload?.direction === 'first' && traceIds.length > 0 && turnsLoaded) {
                    sessionsTracking.conversationLoaded({
                        rowsWaitMs,
                        turnsWaitMs: Math.round(performance.now() - turnsRequestedAt),
                        turnCount: traceIds.length,
                        openedAround: props.aroundTraceId !== null,
                    })
                }
            },
            retryTurns: () =>
                readTurns(
                    [...values.turnSides].filter(([, sides]) => sides.status === 'error').map(([traceId]) => traceId)
                ),
            openTurn: ({ turnId, stepId }) => {
                const row = values.rows.find((candidate) => candidate.traceId === turnId)
                if (row) {
                    actions.openRow({ ...row, stepId })
                }
            },
        }
    }),
    afterMount(({ actions }) => {
        actions.reload()
    }),
])
