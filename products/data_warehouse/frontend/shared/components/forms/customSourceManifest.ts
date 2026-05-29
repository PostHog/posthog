// Pure serialization layer for the Custom REST source manifest builder. Holds no
// React or kea state — `customSourceManifestBuilderLogic` owns the form state and
// `CustomSourceManifestBuilder` renders it. Keeping these functions pure makes the
// build ⇄ parse round-trip directly unit-testable.

export type AuthType = 'none' | 'bearer' | 'api_key' | 'http_basic'

// The backend treats 'query' and 'param' as synonymous (auth.py:41), so we
// only surface 'query' in the UI — the parser still accepts 'param' for
// manifests authored elsewhere.
export type ApiKeyLocation = 'header' | 'query' | 'cookie'

export type Paginator =
    | { type: 'auto' }
    | { type: 'single_page' }
    | { type: 'json_response'; next_url_path?: string }
    | { type: 'cursor'; cursor_path?: string; cursor_param?: string }
    | { type: 'offset'; limit?: number; offset_param?: string; limit_param?: string }
    | { type: 'page_number'; page_param?: string; base_page?: number }
    | { type: 'header_link'; links_next_key?: string }

// Backend IncrementalFieldType values that make sense for REST cursors.
// numeric/objectid are warehouse-specific and intentionally omitted.
export type CursorType = 'datetime' | 'date' | 'timestamp' | 'integer'

export type SortMode = 'asc' | 'desc'

export interface HeaderEntry {
    key: string
    value: string
}

export interface StreamForm {
    name: string
    path: string
    method: 'GET' | 'POST'
    data_selector: string
    primary_key: string
    paginator: Paginator
    sort_mode: SortMode
    incremental_enabled: boolean
    cursor_path: string
    cursor_type: CursorType
    start_param: string
}

export interface ManifestState {
    base_url: string
    auth_type: AuthType
    auth_token: string
    auth_api_key: string
    auth_api_key_name: string
    auth_api_key_location: ApiKeyLocation
    auth_username: string
    auth_password: string
    headers: HeaderEntry[]
    streams: StreamForm[]
}

export interface AuthSecrets {
    auth_token: string
    auth_api_key: string
    auth_password: string
}

export function emptyStream(): StreamForm {
    return {
        name: '',
        path: '',
        method: 'GET',
        data_selector: 'data',
        primary_key: 'id',
        paginator: { type: 'single_page' },
        sort_mode: 'asc',
        incremental_enabled: false,
        cursor_path: '',
        cursor_type: 'datetime',
        start_param: '',
    }
}

export function defaultState(): ManifestState {
    return {
        base_url: '',
        auth_type: 'bearer',
        auth_token: '',
        auth_api_key: '',
        auth_api_key_name: 'Authorization',
        auth_api_key_location: 'header',
        auth_username: '',
        auth_password: '',
        headers: [],
        streams: [emptyStream()],
    }
}

export function buildManifest(state: ManifestState): Record<string, unknown> {
    const headerEntries = state.headers.filter((h) => h.key.trim().length > 0)
    const headerMap: Record<string, string> = {}
    for (const entry of headerEntries) {
        headerMap[entry.key.trim()] = entry.value
    }

    // Auth carries only NON-secret fields. The credential values (token /
    // api_key / password) are written to separate secret form fields by
    // `extractAuthSecrets` so the backend can redact them generically.
    const auth: Record<string, unknown> | undefined = (() => {
        switch (state.auth_type) {
            case 'bearer':
                return { type: 'bearer' }
            case 'api_key':
                return {
                    type: 'api_key',
                    name: state.auth_api_key_name,
                    location: state.auth_api_key_location,
                }
            case 'http_basic':
                return { type: 'http_basic', username: state.auth_username }
            default:
                return undefined
        }
    })()

    const client: Record<string, unknown> = { base_url: state.base_url }
    if (auth) {
        client.auth = auth
    }
    if (Object.keys(headerMap).length > 0) {
        client.headers = headerMap
    }

    const resources = state.streams.map((stream) => {
        const endpoint: Record<string, unknown> = {
            path: stream.path,
            data_selector: stream.data_selector || 'data',
        }
        if (stream.method !== 'GET') {
            endpoint.method = stream.method
        }
        endpoint.paginator = serializePaginator(stream.paginator)
        if (stream.incremental_enabled && stream.cursor_path.trim()) {
            const incremental: Record<string, unknown> = {
                cursor_path: stream.cursor_path.trim(),
                start_param: stream.start_param.trim() || stream.cursor_path.trim(),
            }
            // Only emit cursor_type when it differs from the backend default
            // (datetime) — keeps round-tripped manifests minimal. The Custom
            // source reads it for incremental-field typing and strips it before
            // the REST engine builds its Incremental tracker.
            if (stream.cursor_type !== 'datetime') {
                incremental.cursor_type = stream.cursor_type
            }
            endpoint.incremental = incremental
        }
        const primaryKeys = stream.primary_key
            .split(',')
            .map((part) => part.trim())
            .filter(Boolean)
        const resource: Record<string, unknown> = {
            name: stream.name,
            // Fall back to 'id' when the field is cleared — an empty primary_key
            // array produces a broken resource downstream.
            primary_key: primaryKeys.length === 0 ? 'id' : primaryKeys.length === 1 ? primaryKeys[0] : primaryKeys,
            endpoint,
        }
        // sort_mode only affects incremental resume safety. Emit only when the
        // user explicitly opts into descending order — backend default is asc.
        if (stream.sort_mode === 'desc') {
            resource.sort_mode = 'desc'
        }
        return resource
    })

    return { client, resources }
}

/**
 * The credential values for the currently selected auth type. These are
 * written to separate secret form fields (`payload.auth_*`), never inlined
 * into the manifest — so the backend redacts them with the generic
 * sensitive-field machinery. Non-active auth types yield empty strings.
 */
export function extractAuthSecrets(state: ManifestState): AuthSecrets {
    return {
        auth_token: state.auth_type === 'bearer' ? state.auth_token : '',
        auth_api_key: state.auth_type === 'api_key' ? state.auth_api_key : '',
        auth_password: state.auth_type === 'http_basic' ? state.auth_password : '',
    }
}

function serializePaginator(paginator: Paginator): Record<string, unknown> {
    switch (paginator.type) {
        case 'auto':
            return { type: 'auto' }
        case 'json_response':
            return { type: 'json_response', next_url_path: paginator.next_url_path || 'links.next' }
        case 'cursor':
            return {
                type: 'cursor',
                cursor_path: paginator.cursor_path || 'meta.next_cursor',
                cursor_param: paginator.cursor_param || 'cursor',
            }
        case 'offset':
            return {
                type: 'offset',
                limit: paginator.limit ?? 100,
                offset_param: paginator.offset_param || 'offset',
                limit_param: paginator.limit_param || 'limit',
            }
        case 'page_number':
            return {
                type: 'page_number',
                page_param: paginator.page_param || 'page',
                // base_page is the PageNumberPaginator constructor arg the REST
                // engine expects — initial_page would raise an unexpected-kwarg error.
                base_page: paginator.base_page ?? 1,
            }
        case 'header_link':
            return { type: 'header_link', links_next_key: paginator.links_next_key || 'next' }
        case 'single_page':
        default:
            return { type: 'single_page' }
    }
}

export function parseManifestIntoState(rawJson: string | undefined): ManifestState {
    if (!rawJson) {
        return defaultState()
    }
    try {
        const manifest = JSON.parse(rawJson)
        const client = manifest.client ?? {}
        const auth = client.auth ?? {}
        const authType: AuthType = ['bearer', 'api_key', 'http_basic'].includes(auth.type) ? auth.type : 'none'
        // Backend treats 'param' as a synonym for 'query' — fold it back so the
        // UI never has to surface the dead alias.
        const rawLocation: string = auth.location ?? 'header'
        const normalizedLocation = rawLocation === 'param' ? 'query' : rawLocation
        const apiKeyLocation: ApiKeyLocation = (['header', 'query', 'cookie'] as const).includes(
            normalizedLocation as ApiKeyLocation
        )
            ? (normalizedLocation as ApiKeyLocation)
            : 'header'
        const headerObj: Record<string, string> = client.headers ?? {}
        const headers: HeaderEntry[] = Object.entries(headerObj).map(([key, value]) => ({ key, value: String(value) }))
        const resources: any[] = Array.isArray(manifest.resources) ? manifest.resources : []
        const streams: StreamForm[] = resources.length > 0 ? resources.map(parseStream) : [emptyStream()]
        return {
            base_url: client.base_url ?? '',
            auth_type: authType,
            auth_token: auth.token ?? '',
            auth_api_key: auth.api_key ?? '',
            auth_api_key_name: auth.name ?? 'Authorization',
            auth_api_key_location: apiKeyLocation,
            auth_username: auth.username ?? '',
            auth_password: auth.password ?? '',
            headers,
            streams,
        }
    } catch {
        return defaultState()
    }
}

function parseStream(resource: any): StreamForm {
    const endpoint = resource?.endpoint ?? {}
    const paginatorRaw = endpoint.paginator ?? { type: 'single_page' }
    const paginator: Paginator = [
        'auto',
        'single_page',
        'json_response',
        'cursor',
        'offset',
        'page_number',
        'header_link',
    ].includes(paginatorRaw.type)
        ? paginatorRaw
        : { type: 'single_page' }
    const primaryKey = resource?.primary_key
    const cursorTypeRaw: string = endpoint?.incremental?.cursor_type ?? 'datetime'
    const cursorType: CursorType = (['datetime', 'date', 'timestamp', 'integer'] as const).includes(
        cursorTypeRaw as CursorType
    )
        ? (cursorTypeRaw as CursorType)
        : 'datetime'
    return {
        name: resource?.name ?? '',
        path: endpoint?.path ?? '',
        method: endpoint?.method === 'POST' ? 'POST' : 'GET',
        data_selector: endpoint?.data_selector ?? 'data',
        primary_key: Array.isArray(primaryKey) ? primaryKey.join(', ') : (primaryKey ?? 'id'),
        paginator,
        sort_mode: resource?.sort_mode === 'desc' ? 'desc' : 'asc',
        incremental_enabled: !!endpoint?.incremental,
        cursor_path: endpoint?.incremental?.cursor_path ?? '',
        cursor_type: cursorType,
        start_param: endpoint?.incremental?.start_param ?? '',
    }
}
