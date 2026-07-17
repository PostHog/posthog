// Pure serialization layer for the Custom REST source manifest builder. Holds no
// React or kea state — `customSourceManifestBuilderLogic` owns the form state and
// `CustomSourceManifestBuilder` renders it. Keeping these functions pure makes the
// build ⇄ parse round-trip directly unit-testable.

import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import type { OrganizationType } from '~/types'

// The AI manifest builder needs both the feature flag and the org's AI-data-processing
// consent: the backend (`draft_custom_manifest`) rejects drafting without consent, so the
// frontend must gate on the same pair to avoid offering an intro that can't succeed.
export function isCustomSourceAiBuilderEnabled(
    featureFlags: FeatureFlagsSet,
    currentOrganization: OrganizationType | null
): boolean {
    return (
        !!featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_CUSTOM_SOURCE_AI_BUILDER] &&
        !!currentOrganization?.is_ai_data_processing_approved
    )
}

// Each enum-like value set is declared once as an `as const` tuple; the union type
// and the runtime guard (via `isMember`) are derived from it, so the allowed values
// can't drift between the type, the parser, and the component's select options.
export const AUTH_TYPES = ['none', 'bearer', 'api_key', 'http_basic', 'oauth2'] as const
export type AuthType = (typeof AUTH_TYPES)[number]

// OAuth2 grants for customer-owned clients. `authorization_code` is out of scope
// (needs an interactive consent flow), so only the two non-interactive grants exist;
// the backend rejects any other grant at manifest validation.
export const OAUTH2_GRANT_TYPES = ['client_credentials', 'refresh_token'] as const
export type OAuth2GrantType = (typeof OAUTH2_GRANT_TYPES)[number]

// Where the client credentials travel in the token request (RFC 6749 §2.3.1).
export const OAUTH2_CLIENT_AUTH_METHODS = ['body', 'basic'] as const
export type OAuth2ClientAuthMethod = (typeof OAUTH2_CLIENT_AUTH_METHODS)[number]

/**
 * The auth types the builder's picker should offer. OAuth2 is gated behind its own rollout
 * flag — hidden unless the flag is on, but kept visible when the source *already* uses it, so
 * an existing oauth2 source's type still renders and the select can't silently rewrite it to a
 * different auth type if the flag is later turned off. Lives here (not the component) so the
 * gating branch is unit-tested.
 */
export function visibleAuthTypes(oauth2Enabled: boolean, currentAuthType: AuthType): AuthType[] {
    return AUTH_TYPES.filter((value) => value !== 'oauth2' || oauth2Enabled || currentAuthType === 'oauth2')
}

// The backend treats 'query' and 'param' as synonymous (auth.py:41), so we
// only surface 'query' in the UI — the parser still accepts 'param' for
// manifests authored elsewhere.
export const API_KEY_LOCATIONS = ['header', 'query', 'cookie'] as const
export type ApiKeyLocation = (typeof API_KEY_LOCATIONS)[number]

export const PAGINATOR_TYPES = [
    'single_page',
    'json_response',
    'cursor',
    'offset',
    'page_number',
    'header_link',
] as const
export type PaginatorType = (typeof PAGINATOR_TYPES)[number]

export type Paginator =
    | { type: 'single_page' }
    | { type: 'json_response'; next_url_path?: string }
    | { type: 'cursor'; cursor_path?: string; cursor_param?: string }
    | { type: 'offset'; limit?: number; offset_param?: string; limit_param?: string }
    | { type: 'page_number'; page_param?: string; base_page?: number }
    | { type: 'header_link'; links_next_key?: string }

// Backend IncrementalFieldType values that make sense for REST cursors.
// numeric/objectid are warehouse-specific and intentionally omitted.
export const CURSOR_TYPES = ['datetime', 'date', 'timestamp', 'integer'] as const
export type CursorType = (typeof CURSOR_TYPES)[number]

export const SORT_MODES = ['asc', 'desc'] as const
export type SortMode = (typeof SORT_MODES)[number]

// Default field values per paginator type — the single source shared by
// `serializePaginator` (build-time fallbacks), the form's paginator type-switch,
// and the input placeholders, so a default can't drift between them.
export const PAGINATOR_DEFAULTS = {
    json_response: { next_url_path: 'links.next' },
    cursor: { cursor_path: 'meta.next_cursor', cursor_param: 'cursor' },
    offset: { limit: 100, offset_param: 'offset', limit_param: 'limit' },
    page_number: { page_param: 'page', base_page: 1 },
    header_link: { links_next_key: 'next' },
} as const

function isMember<T extends string>(values: readonly T[], value: string): value is T {
    return (values as readonly string[]).includes(value)
}

// Stable client-only ids so React lists keep input/focus state attached to the
// right row across mid-list removals. Never serialized into the manifest.
let tableIdSeq = 0
let headerIdSeq = 0
export function nextTableId(): string {
    return `table-${tableIdSeq++}`
}
export function nextHeaderId(): string {
    return `header-${headerIdSeq++}`
}

export interface HeaderEntry {
    id: string
    key: string
    value: string
}

export interface TableForm {
    id: string
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
    // strftime pattern for the outgoing watermark; empty → ISO-8601 default
    datetime_format: string
    // Fan-out (parent/child): when `parent_table` is set, PostHog fetches that
    // table first and calls this one once per parent row, injecting
    // `parent_resolve_field` into the `{parent_path_param}` placeholder in the
    // path. `include_from_parent` lists parent fields copied onto each child row.
    // Empty `parent_table` means a top-level table.
    parent_table: string
    parent_resolve_field: string
    parent_path_param: string
    include_from_parent: string
    // Raw-authored `endpoint.params` entries the builder has no UI for (static
    // query params, the engine's incremental specs, extra resolve params).
    // Carried verbatim through parse → build so editing a table in the builder
    // never silently drops a query param the manifest author wrote by hand.
    passthrough_params: Record<string, unknown>
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
    // OAuth2 (customer-owned client). The non-secret fields go into `client.auth` in the
    // manifest; the secrets (`oauth2_client_secret`, `oauth2_refresh_token`) flow via
    // `extractAuthSecrets` into separate `auth_oauth2_*` form fields, never the manifest.
    oauth2_token_url: string
    oauth2_client_id: string
    oauth2_client_secret: string
    oauth2_grant_type: OAuth2GrantType
    oauth2_scopes: string
    oauth2_refresh_token: string
    // Advanced (scalar) knobs for the provider long tail — empty means "use the backend default".
    oauth2_access_token_name: string
    oauth2_expires_in_name: string
    oauth2_expiry_date_format: string
    oauth2_client_auth_method: OAuth2ClientAuthMethod
    // Advanced dict knobs with no dedicated builder UI (e.g. Auth0's `audience`, custom token
    // headers). Carried verbatim through parse → build, like `passthrough_params` for tables,
    // so an AI-drafted or hand-authored manifest doesn't lose them when edited in the builder.
    oauth2_extra_token_request_params: Record<string, string>
    oauth2_token_request_headers: Record<string, string>
    headers: HeaderEntry[]
    tables: TableForm[]
}

// Keys mirror the backend `auth_*` secret config field names exactly — they're written
// straight to `payload.<key>` by the builder logic, so a rename here breaks redaction.
export interface AuthSecrets {
    auth_token: string
    auth_api_key: string
    auth_password: string
    auth_oauth2_client_secret: string
    auth_oauth2_refresh_token: string
}

export function emptyHeader(): HeaderEntry {
    return { id: nextHeaderId(), key: '', value: '' }
}

// The cleared (top-level) state of every parent-dependency field. Single
// source for the three places that reset a dependency — emptyTable, removing
// a parent table, and the builder's "None" selection — so a new parent field
// only needs a default here.
export const EMPTY_PARENT_FIELDS = {
    parent_table: '',
    parent_resolve_field: '',
    parent_path_param: '',
    include_from_parent: '',
} satisfies Partial<TableForm>

export function emptyTable(): TableForm {
    return {
        id: nextTableId(),
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
        datetime_format: '',
        passthrough_params: {},
        ...EMPTY_PARENT_FIELDS,
    }
}

function splitCsv(value: string): string[] {
    return value
        .split(',')
        .map((part) => part.trim())
        .filter(Boolean)
}

/**
 * Names of the tables that `tables[index]` may depend on: named, not itself,
 * and top-level — nesting is capped at one level (a table that already has a
 * parent can't be a parent itself), mirroring the backend validation. This also
 * makes cycles structurally impossible to build in the UI.
 */
export function eligibleParentTables(tables: TableForm[], index: number): string[] {
    return tables
        .filter(
            (other, otherIndex) =>
                otherIndex !== index && other.name.trim().length > 0 && other.parent_table.trim().length === 0
        )
        .map((other) => other.name)
}

/**
 * Applies a patch to one table. Renaming a table follows through to children
 * that reference it via `parent_table` — otherwise their dependency would
 * dangle silently and only fail at save time.
 */
export function updateTableInList(tables: TableForm[], index: number, patch: Partial<TableForm>): TableForm[] {
    const oldName = tables[index]?.name
    const updated = tables.map((table, i) => (i === index ? { ...table, ...patch } : table))
    const newName = patch.name
    if (newName === undefined || !oldName || newName === oldName) {
        return updated
    }
    return updated.map((table, i) =>
        i !== index && table.parent_table === oldName ? { ...table, parent_table: newName } : table
    )
}

/**
 * Removes a table. Children that depended on it have the parent dependency
 * cleared (back to top-level) so they don't reference a table that no longer
 * exists.
 */
export function removeTableFromList(tables: TableForm[], index: number): TableForm[] {
    const removedName = tables[index]?.name
    const remaining = tables.filter((_, i) => i !== index)
    if (!removedName || remaining.some((table) => table.name === removedName)) {
        return remaining
    }
    return remaining.map((table) => (table.parent_table === removedName ? { ...table, ...EMPTY_PARENT_FIELDS } : table))
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
        oauth2_token_url: '',
        oauth2_client_id: '',
        oauth2_client_secret: '',
        oauth2_grant_type: 'client_credentials',
        oauth2_scopes: '',
        oauth2_refresh_token: '',
        oauth2_access_token_name: '',
        oauth2_expires_in_name: '',
        oauth2_expiry_date_format: '',
        oauth2_client_auth_method: 'body',
        oauth2_extra_token_request_params: {},
        oauth2_token_request_headers: {},
        headers: [],
        tables: [emptyTable()],
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
            case 'oauth2': {
                // Only NON-secret oauth fields go into the manifest. client_secret and
                // refresh_token flow via extractAuthSecrets into separate form fields.
                const oauth: Record<string, unknown> = {
                    type: 'oauth2',
                    client_id: state.oauth2_client_id,
                    token_url: state.oauth2_token_url,
                    grant_type: state.oauth2_grant_type,
                }
                // Keep scopes a single space-separated string end-to-end — never split/rejoin.
                if (state.oauth2_scopes.trim()) {
                    oauth.scopes = state.oauth2_scopes.trim()
                }
                // Advanced knobs: emit only when set so the common manifest stays minimal.
                if (state.oauth2_access_token_name.trim()) {
                    oauth.access_token_name = state.oauth2_access_token_name.trim()
                }
                if (state.oauth2_expires_in_name.trim()) {
                    oauth.expires_in_name = state.oauth2_expires_in_name.trim()
                }
                if (state.oauth2_expiry_date_format.trim()) {
                    oauth.expiry_date_format = state.oauth2_expiry_date_format.trim()
                }
                if (state.oauth2_client_auth_method !== 'body') {
                    oauth.client_auth_method = state.oauth2_client_auth_method
                }
                if (Object.keys(state.oauth2_extra_token_request_params).length > 0) {
                    oauth.extra_token_request_params = state.oauth2_extra_token_request_params
                }
                if (Object.keys(state.oauth2_token_request_headers).length > 0) {
                    oauth.token_request_headers = state.oauth2_token_request_headers
                }
                return oauth
            }
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

    const resources = state.tables.map((table) => {
        const endpoint: Record<string, unknown> = {
            path: table.path,
            data_selector: table.data_selector || 'data',
        }
        if (table.method !== 'GET') {
            endpoint.method = table.method
        }
        endpoint.paginator = serializePaginator(table.paginator)
        if (table.incremental_enabled && table.cursor_path.trim()) {
            const incremental: Record<string, unknown> = {
                cursor_path: table.cursor_path.trim(),
                start_param: table.start_param.trim() || table.cursor_path.trim(),
            }
            // Only emit cursor_type when it differs from the backend default
            // (datetime) — keeps round-tripped manifests minimal. The Custom
            // source reads it for incremental-field typing and strips it before
            // the REST engine builds its Incremental tracker.
            if (table.cursor_type !== 'datetime') {
                incremental.cursor_type = table.cursor_type
            }
            if (table.datetime_format.trim()) {
                incremental.datetime_format = table.datetime_format.trim()
            }
            endpoint.incremental = incremental
        }
        // Fan-out: bind the parent's field into the path placeholder via a
        // `resolve` param, merged onto the raw-authored params the builder has
        // no UI for. The dependency is emitted whenever a parent is selected,
        // even half-filled: an incomplete dependency must fail backend validation
        // loudly (the builder UI flags the missing pieces inline) rather than be
        // silently dropped — that would sync this table as an unrelated
        // top-level endpoint.
        const parentTable = table.parent_table.trim()
        const params: Record<string, unknown> = { ...table.passthrough_params }
        if (parentTable) {
            params[table.parent_path_param.trim()] = {
                type: 'resolve',
                resource: parentTable,
                field: table.parent_resolve_field.trim(),
            }
        }
        if (Object.keys(params).length > 0) {
            endpoint.params = params
        }
        const primaryKeys = splitCsv(table.primary_key)
        const resource: Record<string, unknown> = {
            name: table.name,
            // Fall back to 'id' when the field is cleared — an empty primary_key
            // array produces a broken resource downstream.
            primary_key: primaryKeys.length === 0 ? 'id' : primaryKeys.length === 1 ? primaryKeys[0] : primaryKeys,
            endpoint,
        }
        const includeFromParent = splitCsv(table.include_from_parent)
        if (parentTable && includeFromParent.length > 0) {
            resource.include_from_parent = includeFromParent
        }
        // sort_mode only affects incremental resume safety. Emit only when the
        // user explicitly opts into descending order — backend default is asc.
        if (table.sort_mode === 'desc') {
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
        auth_oauth2_client_secret: state.auth_type === 'oauth2' ? state.oauth2_client_secret : '',
        // The refresh token only applies to the refresh_token grant — keep it empty otherwise so
        // switching auth type or grant never carries a stale secret through to the backend.
        auth_oauth2_refresh_token:
            state.auth_type === 'oauth2' && state.oauth2_grant_type === 'refresh_token'
                ? state.oauth2_refresh_token
                : '',
    }
}

function serializePaginator(paginator: Paginator): Record<string, unknown> {
    switch (paginator.type) {
        case 'json_response':
            return {
                type: 'json_response',
                next_url_path: paginator.next_url_path || PAGINATOR_DEFAULTS.json_response.next_url_path,
            }
        case 'cursor':
            return {
                type: 'cursor',
                cursor_path: paginator.cursor_path || PAGINATOR_DEFAULTS.cursor.cursor_path,
                cursor_param: paginator.cursor_param || PAGINATOR_DEFAULTS.cursor.cursor_param,
            }
        case 'offset':
            return {
                type: 'offset',
                limit: paginator.limit ?? PAGINATOR_DEFAULTS.offset.limit,
                offset_param: paginator.offset_param || PAGINATOR_DEFAULTS.offset.offset_param,
                limit_param: paginator.limit_param || PAGINATOR_DEFAULTS.offset.limit_param,
            }
        case 'page_number':
            return {
                type: 'page_number',
                page_param: paginator.page_param || PAGINATOR_DEFAULTS.page_number.page_param,
                // base_page is the PageNumberPaginator constructor arg the REST
                // engine expects — initial_page would raise an unexpected-kwarg error.
                base_page: paginator.base_page ?? PAGINATOR_DEFAULTS.page_number.base_page,
            }
        case 'header_link':
            return {
                type: 'header_link',
                links_next_key: paginator.links_next_key || PAGINATOR_DEFAULTS.header_link.links_next_key,
            }
        case 'single_page':
        default:
            return { type: 'single_page' }
    }
}

type RawObject = Record<string, unknown>

function asObject(value: unknown): RawObject {
    return typeof value === 'object' && value !== null ? (value as RawObject) : {}
}

function asString(value: unknown, fallback = ''): string {
    return typeof value === 'string' ? value : fallback
}

// OAuth2 token-request params/headers are string-valued by definition (form body params and HTTP
// header values). Coerce scalar values to string and drop non-scalars so the parsed state matches
// the backend's `dict[str, str]` — a non-string value from a hand/AI-authored manifest is normalized
// here instead of silently round-tripping into a backend validation error.
function asStringRecord(value: unknown): Record<string, string> {
    const result: Record<string, string> = {}
    for (const [key, raw] of Object.entries(asObject(value))) {
        if (typeof raw === 'string') {
            result[key] = raw
        } else if (typeof raw === 'number' || typeof raw === 'boolean') {
            result[key] = String(raw)
        }
    }
    return result
}

export function parseManifestIntoState(rawJson: string | undefined): ManifestState {
    if (!rawJson) {
        return defaultState()
    }
    let parsed: unknown
    try {
        parsed = JSON.parse(rawJson)
    } catch {
        return defaultState()
    }
    const manifest = asObject(parsed)
    const client = asObject(manifest.client)
    const auth = asObject(client.auth)
    const authTypeRaw = asString(auth.type)
    // 'none' is the fallback for any unsupported auth type; it carries no
    // credential fields so the token/api_key/password reads below stay empty.
    const authType: AuthType = isMember(AUTH_TYPES, authTypeRaw) ? authTypeRaw : 'none'
    // Backend treats 'param' as a synonym for 'query' — fold it back so the
    // UI never has to surface the dead alias.
    const rawLocation = asString(auth.location, 'header')
    const normalizedLocation = rawLocation === 'param' ? 'query' : rawLocation
    const apiKeyLocation: ApiKeyLocation = isMember(API_KEY_LOCATIONS, normalizedLocation)
        ? normalizedLocation
        : 'header'
    const oauth2GrantRaw = asString(auth.grant_type, 'client_credentials')
    const oauth2GrantType: OAuth2GrantType = isMember(OAUTH2_GRANT_TYPES, oauth2GrantRaw)
        ? oauth2GrantRaw
        : 'client_credentials'
    const oauth2AuthMethodRaw = asString(auth.client_auth_method, 'body')
    const oauth2ClientAuthMethod: OAuth2ClientAuthMethod = isMember(OAUTH2_CLIENT_AUTH_METHODS, oauth2AuthMethodRaw)
        ? oauth2AuthMethodRaw
        : 'body'
    const headerObj = asObject(client.headers)
    const headers: HeaderEntry[] = Object.entries(headerObj).map(([key, value]) => ({
        id: nextHeaderId(),
        key,
        value: String(value),
    }))
    const resources: unknown[] = Array.isArray(manifest.resources) ? manifest.resources : []
    const tables: TableForm[] = resources.length > 0 ? resources.map(parseTable) : [emptyTable()]
    return {
        base_url: asString(client.base_url),
        auth_type: authType,
        auth_token: asString(auth.token),
        auth_api_key: asString(auth.api_key),
        auth_api_key_name: asString(auth.name, 'Authorization'),
        auth_api_key_location: apiKeyLocation,
        auth_username: asString(auth.username),
        auth_password: asString(auth.password),
        // Secrets are never in the manifest — they live in separate config fields — so they
        // parse back empty and the user re-enters them (or they were already redacted away).
        oauth2_token_url: asString(auth.token_url),
        oauth2_client_id: asString(auth.client_id),
        oauth2_client_secret: '',
        oauth2_grant_type: oauth2GrantType,
        oauth2_scopes: asString(auth.scopes),
        oauth2_refresh_token: '',
        oauth2_access_token_name: asString(auth.access_token_name),
        oauth2_expires_in_name: asString(auth.expires_in_name),
        oauth2_expiry_date_format: asString(auth.expiry_date_format),
        oauth2_client_auth_method: oauth2ClientAuthMethod,
        oauth2_extra_token_request_params: asStringRecord(auth.extra_token_request_params),
        oauth2_token_request_headers: asStringRecord(auth.token_request_headers),
        headers,
        tables,
    }
}

function parseTable(resource: unknown): TableForm {
    const r = asObject(resource)
    const endpoint = asObject(r.endpoint)
    const paginatorRaw = asObject(endpoint.paginator)
    const paginatorType = asString(paginatorRaw.type)
    const paginator: Paginator = isMember(PAGINATOR_TYPES, paginatorType)
        ? (paginatorRaw as Paginator)
        : { type: 'single_page' }
    const incremental = asObject(endpoint.incremental)
    const cursorTypeRaw = asString(incremental.cursor_type, 'datetime')
    const cursorType: CursorType = isMember(CURSOR_TYPES, cursorTypeRaw) ? cursorTypeRaw : 'datetime'
    const primaryKey = r.primary_key
    // Recover a fan-out dependency from the first `resolve` param: its key is the
    // path placeholder, and it names the parent table + the parent field bound in.
    // Every other params entry (static query params, incremental specs, extra
    // resolve params on a malformed manifest) is preserved verbatim so a builder
    // edit can't silently drop it.
    const params = asObject(endpoint.params)
    let parentTable = ''
    let parentResolveField = ''
    let parentPathParam = ''
    const passthroughParams: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(params)) {
        const spec = asObject(value)
        if (spec.type === 'resolve' && !parentPathParam) {
            parentPathParam = key
            parentTable = asString(spec.resource)
            parentResolveField = asString(spec.field)
        } else {
            passthroughParams[key] = value
        }
    }
    const includeFromParent = Array.isArray(r.include_from_parent)
        ? (r.include_from_parent as unknown[]).map((field) => String(field)).join(', ')
        : ''
    return {
        id: nextTableId(),
        name: asString(r.name),
        path: asString(endpoint.path),
        method: asString(endpoint.method) === 'POST' ? 'POST' : 'GET',
        data_selector: asString(endpoint.data_selector, 'data'),
        primary_key: Array.isArray(primaryKey) ? primaryKey.join(', ') : asString(primaryKey, 'id'),
        paginator,
        sort_mode: asString(r.sort_mode) === 'desc' ? 'desc' : 'asc',
        incremental_enabled: !!endpoint.incremental,
        cursor_path: asString(incremental.cursor_path),
        cursor_type: cursorType,
        start_param: asString(incremental.start_param),
        datetime_format: asString(incremental.datetime_format),
        parent_table: parentTable,
        parent_resolve_field: parentResolveField,
        parent_path_param: parentPathParam,
        include_from_parent: includeFromParent,
        passthrough_params: passthroughParams,
    }
}
