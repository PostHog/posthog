import { ApiConfig } from 'lib/api'
import { objectsEqual } from 'lib/utils/objects'
import { urls } from 'scenes/urls'

import { aiObservabilityTracesPreviewsCreate } from '../../generated/api'
import type { AiObservabilityTracesListParams, TraceListItemApi, TracePreviewApi } from '../../generated/api.schemas'
import { ListRequestScope, listRequestParams } from '../lists/cursorPaging'
import type { ListFilters } from '../lists/listFiltersLogic'
import type { ListScopeKind } from '../lists/listScopes'
import type { CellLoads, TraceCellLoad } from '../shared/cellLoads'
import { rangeTooLongDetail } from '../shared/rangeTooLong'
import { readOrFailure, toLoadFailure } from '../shared/readOrFailure'
import { shellHref, shellLinkParams } from '../shell/shellNavigation'
import { withRawParams } from '../trace/rawSearchParam'
import { TRACE_DRAWER_PARAMS } from '../trace/traceDrawerRows'
import type { TraceListRow } from '../trace/traceListRows'
import type { LoadFailure } from '../trace/types'

export const RECENT_TRACES_LIMIT = 5

export type DiagnosticsDrawerParams = Pick<
    AiObservabilityTracesListParams,
    'date_from' | 'date_to' | 'properties' | 'filter_test_accounts'
>

// Another entity opens on its own, so a trace opened over the entity before it closes.
export const CLOSED_TRACE_DRAWER: Record<string, undefined> = Object.fromEntries(
    TRACE_DRAWER_PARAMS.map((name) => [name, undefined])
)

/** The open entity's key, from the list's `key`, with the selection to read it in. */
export interface EntityRequest {
    key: string
    params: DiagnosticsDrawerParams
}

/** The row an entity opened from, with the selection the row was counted in. */
export interface EntitySeed<Item> {
    item: Item
    params: DiagnosticsDrawerParams
}

export interface PreviewReadActions {
    previewsRequested: (traceIds: string[]) => void
    previewsFailed: (traceIds: string[]) => void
    previewsLoaded: (items: TracePreviewApi[]) => void
}

/** A value read for one request, so a value read for another entity or another selection is never shown. */
export interface ReadFor<T> {
    request: unknown
    value: T
}

/** `not_found` is an entity with nothing in the selection, which reading again cannot change. */
export type DetailLoad<T> = TraceCellLoad<T> | { status: 'not_found' }

/** The selection the list counted a row in, without the list's search, so the drawer and its traces agree with it. */
export function drawerReadParams(
    filters: ListFilters,
    scope: Omit<ListRequestScope, 'searchEnabled'>
): DiagnosticsDrawerParams {
    const { date_from, date_to, properties, filter_test_accounts } = listRequestParams(filters, {
        ...scope,
        searchEnabled: false,
    })
    return { date_from, date_to, properties, filter_test_accounts }
}

// A read that is no longer the latest drops its answer and its failure, so neither lands over the newer one.
export async function latest<T>(read: Promise<T>, breakpoint: () => void): Promise<T> {
    return await read.finally(() => breakpoint())
}

export function valueFor<T>(read: ReadFor<T> | null, request: unknown): T | null {
    return read && request && objectsEqual(read.request, request) ? read.value : null
}

export function readLoadOf<T>(value: T | null, failed: boolean): TraceCellLoad<T> {
    if (failed) {
        return { status: 'error' }
    }
    return value === null ? { status: 'loading' } : { status: 'ready', value }
}

export function detailLoadOf<T>(value: T | null, failure: LoadFailure | null): DetailLoad<T> {
    return failure === 'not_found' ? { status: 'not_found' } : readLoadOf(value, failure !== null)
}

export function traceRowOf(item: TraceListItemApi): TraceListRow {
    return {
        traceId: item.id,
        timestamp: item.createdAt,
        stepId: null,
        overview: item,
        defaultStepId: item.defaultNodeId ?? undefined,
    }
}

/**
 * The traces list scoped to an entity, in the same range, filters and test-account switch. A diagnostics list's own
 * view means nothing there, and the diagnostics lists apply no list's search, so the link drops the view and every
 * `*_search` param and shows every trace the row counts.
 */
export function scopedTracesHref(
    location: { pathname: string; search: string },
    searchParams: Record<string, unknown>,
    scope: { kind: ListScopeKind; value: string }
): string {
    const linkParams = Object.entries(shellLinkParams(withRawParams(searchParams, location.search)))
    return shellHref(urls.aiObservabilityTraces(), {
        ...Object.fromEntries(linkParams.filter(([name]) => name !== 'view' && !name.endsWith('_search'))),
        [scope.kind]: scope.value,
    })
}

/** The drawer's row: the detail read for the request, else the row it opened from while that row's selection holds. */
export function shownItem<Item extends { key: string }>(
    detailItem: Item | null,
    seed: EntitySeed<Item> | null,
    request: EntityRequest | null,
    detailFailure: LoadFailure | null
): Item | null {
    if (detailFailure === 'not_found') {
        return null
    }
    const seedIsCurrent = !!seed && seed.item.key === request?.key && objectsEqual(seed.params, request.params)
    return detailItem ?? (seedIsCurrent ? seed.item : null)
}

/**
 * The first row with the open key, whatever selection read it. A key names one message or tool in every selection, so
 * the row's text is the open entity's, which scopes its traces.
 */
export function rowWithKey<Item extends { key: string }>(
    openKey: string | null,
    rows: (Item | null | undefined)[]
): Item | null {
    return rows.find((row): row is Item => !!row && row.key === openKey) ?? null
}

/** Recent traces need the entity's text, so without it they follow the detail read that would give it. */
export function recentTracesLoadOf<T>(
    value: T[] | null,
    failed: boolean,
    textKnown: boolean,
    detailFailure: LoadFailure | null
): TraceCellLoad<T[]> {
    if (!textKnown && detailFailure) {
        return detailFailure === 'not_found' ? { status: 'ready', value: [] } : { status: 'error' }
    }
    return readLoadOf(value, failed)
}

/** Whether a failed read is one to report: a range too long shows its own message, and nothing found is no failure. */
export function isReportedFailure(errorObject: unknown): boolean {
    return toLoadFailure(errorObject) === 'failed' && rangeTooLongDetail(errorObject) === null
}

export function tracesToPreview(traces: TraceListItemApi[], previews: CellLoads<TracePreviewApi>): string[] {
    return traces.map((trace) => trace.id).filter((id) => previews.get(id)?.status !== 'ready')
}

/** Reads the inputs of the recent traces that have none yet, and drops the answer once a newer read replaces it. */
export async function readMissingPreviews(
    traces: TraceListItemApi[],
    previews: CellLoads<TracePreviewApi>,
    actions: PreviewReadActions,
    breakpoint: () => void
): Promise<void> {
    const traceIds = tracesToPreview(traces, previews)
    if (traceIds.length === 0) {
        return
    }
    actions.previewsRequested(traceIds)
    const result = await readOrFailure(
        aiObservabilityTracesPreviewsCreate(String(ApiConfig.getCurrentProjectId()), { trace_ids: traceIds })
    )
    breakpoint()
    if ('failure' in result) {
        actions.previewsFailed(traceIds)
    } else {
        actions.previewsLoaded(result.value.items)
    }
}
