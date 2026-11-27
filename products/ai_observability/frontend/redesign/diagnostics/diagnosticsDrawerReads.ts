import { ApiConfig, isAbortError } from 'lib/api'
import { objectsEqual } from 'lib/utils/objects'
import { urls } from 'scenes/urls'

import { aiObservabilityTracesPreviewsCreate } from '../../generated/api'
import type { AiObservabilityTracesListParams, TraceListItemApi, TracePreviewApi } from '../../generated/api.schemas'
import { ListRequestScope, listRequestParams } from '../lists/cursorPaging'
import type { ListFilters } from '../lists/listFiltersLogic'
import type { ListScopeKind } from '../lists/listScopes'
import type { CellLoads, TraceCellLoad } from '../shared/cellLoads'
import { createCellReader } from '../shared/cellReader'
import { rangeTooLongDetail } from '../shared/rangeTooLong'
import { toLoadFailure } from '../shared/readOrFailure'
import { shellHref, shellLinkParams } from '../shell/shellNavigation'
import { withRawParams } from '../trace/rawSearchParam'
import { TRACE_DRAWER_PARAMS } from '../trace/traceDrawerRows'
import type { TraceListRow } from '../trace/traceListRows'
import type { LoadFailure } from '../trace/types'

export const RECENT_TRACES_LIMIT = 5
// The server hands out entity keys as unpadded base64url.
const ENTITY_KEY = /^[A-Za-z0-9_-]+$/

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

/** The key in a URL param when it can be a key the server handed out. The reads put it in an API path, so a value with
 * any other character, such as `../`, never reaches a request. */
export function entityKeyParam(value: string | null): string | null {
    return value !== null && ENTITY_KEY.test(value) ? value : null
}

/**
 * The signal of a drawer read under `key`. The next read under the same key aborts it, as does `dispose(key)` and the
 * logic's unmount, so a superseded scan frees its query slot. A hidden tab keeps it going.
 */
export function replaceableRead(cache: Record<string, any>, key: string): AbortSignal {
    const controller = new AbortController()
    cache.disposables.add(() => () => controller.abort(), key, { pauseOnPageHidden: false })
    return controller.signal
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

/** Whether a failed read is one to report: a range too long shows its own message, and neither nothing found nor an
 * aborted read is a failure. */
export function isReportedFailure(errorObject: unknown): boolean {
    return (
        !isAbortError(errorObject) &&
        toLoadFailure(errorObject) === 'failed' &&
        rangeTooLongDetail(errorObject) === null
    )
}

/** The traces whose preview is neither read nor in flight, so a failed one is read again. */
export function tracesToPreview(traces: TraceListItemApi[], previews: CellLoads<TracePreviewApi>): string[] {
    return traces
        .map((trace) => trace.id)
        .filter((id) => {
            const status = previews.get(id)?.status
            return status !== 'ready' && status !== 'loading'
        })
}

/**
 * Reads the previews of the traces that have none yet or whose read failed, for every list of traces a drawer shows.
 * A preview belongs to its trace whatever list shows it, so lists that share a trace share its read.
 */
export function createPreviewReader(
    cache: Record<string, any>,
    actions: PreviewReadActions
): (traces: TraceListItemApi[], previews: CellLoads<TracePreviewApi>) => Promise<void> {
    const readCells = createCellReader<string, 'previews', TracePreviewApi>({
        cache,
        idOf: (traceId) => traceId,
        itemIdOf: (preview) => preview.traceId,
        requested: (_read, traceIds) => actions.previewsRequested(traceIds),
        failed: (_read, traceIds) => actions.previewsFailed(traceIds),
    })
    return (traces, previews) =>
        readCells(
            'previews',
            tracesToPreview(traces, previews),
            (traceIds) =>
                aiObservabilityTracesPreviewsCreate(String(ApiConfig.getCurrentProjectId()), { trace_ids: traceIds }),
            actions.previewsLoaded
        )
}
