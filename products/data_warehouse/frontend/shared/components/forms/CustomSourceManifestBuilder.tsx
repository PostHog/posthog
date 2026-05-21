import { FieldName } from 'kea-forms'
import { useEffect, useMemo, useRef, useState } from 'react'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

type AuthType = 'none' | 'bearer' | 'api_key' | 'http_basic'
type Paginator =
    | { type: 'single_page' }
    | { type: 'json_response'; next_url_path?: string }
    | { type: 'cursor'; cursor_path?: string; cursor_param?: string }
    | { type: 'offset'; limit?: number; offset_param?: string; limit_param?: string }
    | { type: 'page_number'; page_param?: string; initial_page?: number }
    | { type: 'header_link'; links_next_key?: string }

interface HeaderEntry {
    key: string
    value: string
}

interface StreamForm {
    name: string
    path: string
    method: 'GET' | 'POST'
    data_selector: string
    primary_key: string
    paginator: Paginator
    incremental_enabled: boolean
    cursor_path: string
    start_param: string
}

export interface ManifestState {
    base_url: string
    auth_type: AuthType
    auth_token: string
    auth_api_key: string
    auth_api_key_name: string
    auth_username: string
    auth_password: string
    headers: HeaderEntry[]
    streams: StreamForm[]
}

const PAGINATOR_OPTIONS: { value: Paginator['type']; label: string }[] = [
    { value: 'single_page', label: 'Single page (no pagination)' },
    { value: 'json_response', label: 'JSON body next-URL' },
    { value: 'cursor', label: 'Cursor in JSON body' },
    { value: 'offset', label: 'Offset / limit query params' },
    { value: 'page_number', label: 'Page number query param' },
    { value: 'header_link', label: 'Link header (RFC 5988)' },
]

const AUTH_OPTIONS: { value: AuthType; label: string }[] = [
    { value: 'none', label: 'No auth' },
    { value: 'bearer', label: 'Bearer token' },
    { value: 'api_key', label: 'API key (header)' },
    { value: 'http_basic', label: 'HTTP basic auth' },
]

function emptyStream(): StreamForm {
    return {
        name: '',
        path: '',
        method: 'GET',
        data_selector: 'data',
        primary_key: 'id',
        paginator: { type: 'single_page' },
        incremental_enabled: false,
        cursor_path: '',
        start_param: '',
    }
}

function defaultState(): ManifestState {
    return {
        base_url: '',
        auth_type: 'bearer',
        auth_token: '',
        auth_api_key: '',
        auth_api_key_name: 'Authorization',
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
                return { type: 'api_key', name: state.auth_api_key_name, location: 'header' }
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
            endpoint.incremental = {
                cursor_path: stream.cursor_path.trim(),
                start_param: stream.start_param.trim() || stream.cursor_path.trim(),
            }
        }
        const primaryKeys = stream.primary_key
            .split(',')
            .map((part) => part.trim())
            .filter(Boolean)
        return {
            name: stream.name,
            primary_key: primaryKeys.length === 1 ? primaryKeys[0] : primaryKeys,
            endpoint,
        }
    })

    return { client, resources }
}

export interface AuthSecrets {
    auth_token: string
    auth_api_key: string
    auth_password: string
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
                initial_page: paginator.initial_page ?? 1,
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
    return {
        name: resource?.name ?? '',
        path: endpoint?.path ?? '',
        method: endpoint?.method === 'POST' ? 'POST' : 'GET',
        data_selector: endpoint?.data_selector ?? 'data',
        primary_key: Array.isArray(primaryKey) ? primaryKey.join(', ') : (primaryKey ?? 'id'),
        paginator,
        incremental_enabled: !!endpoint?.incremental,
        cursor_path: endpoint?.incremental?.cursor_path ?? '',
        start_param: endpoint?.incremental?.start_param ?? '',
    }
}

export interface CustomSourceManifestBuilderProps {
    initialManifestJson?: string
    /**
     * Writes the serialized manifest into the outer form. Differs between
     * mount sites: the wizard provides
     * `sourceWizardLogic.actions.setSourceConnectionDetailsValue`, and the
     * configuration page (existing source) provides
     * `sourceSettingsLogic.actions.setSourceConfigValue`. Either accepts a
     * `(path, value)` signature.
     */
    setValue: (path: FieldName, value: unknown) => void
}

/**
 * Visual builder for the Custom REST source's manifest. Maintains its own
 * structured form state (base URL, auth, headers, streams) and writes it to
 * the outer form as `payload.manifest_json` (the non-secret RESTAPIConfig
 * structure) plus separate `payload.auth_*` secret fields for the credentials.
 *
 * The backend rejoins the two before handing the config to `rest_api_resource()`.
 * Keeping credentials out of the manifest lets the generic API layer redact
 * them with no Custom-source-specific serializer code.
 */
export function CustomSourceManifestBuilder({
    initialManifestJson,
    setValue,
}: CustomSourceManifestBuilderProps): JSX.Element {
    const [state, setState] = useState<ManifestState>(() => parseManifestIntoState(initialManifestJson))

    // The configuration page loads `source.job_inputs` via a poll, so the
    // first render typically has no manifest and a real one arrives a beat
    // later. Re-parse when the prop changes (but only on *prop* changes —
    // we ignore our own re-renders to avoid wiping the user's edits).
    const lastSeenInitialRef = useRef(initialManifestJson)
    useEffect(() => {
        if (initialManifestJson !== lastSeenInitialRef.current) {
            lastSeenInitialRef.current = initialManifestJson
            if (initialManifestJson) {
                setState(parseManifestIntoState(initialManifestJson))
            }
        }
    }, [initialManifestJson])

    // Only write to the outer form once the user has actually engaged — either
    // by typing, or by an initial manifest arriving from the parent. Without
    // this guard, the configuration page would clobber the saved manifest with
    // empty defaults on the render that sits between mount and prop-arrival.
    const [hasContent, setHasContent] = useState<boolean>(() => !!initialManifestJson)
    useEffect(() => {
        if (initialManifestJson) {
            setHasContent(true)
        }
    }, [initialManifestJson])

    const manifestJson = useMemo(() => JSON.stringify(buildManifest(state), null, 2), [state])
    const authSecrets = useMemo(() => extractAuthSecrets(state), [state])

    useEffect(() => {
        if (!hasContent) {
            return
        }
        setValue(['payload', 'manifest_json'] as FieldName, manifestJson)
        // Secrets go to their own fields so the backend redacts them generically;
        // the manifest itself stays non-secret and round-trips to the config tab.
        setValue(['payload', 'auth_token'] as FieldName, authSecrets.auth_token)
        setValue(['payload', 'auth_api_key'] as FieldName, authSecrets.auth_api_key)
        setValue(['payload', 'auth_password'] as FieldName, authSecrets.auth_password)
    }, [manifestJson, authSecrets, hasContent, setValue])

    // Wrap every mutation so a user edit also unblocks the setValue effect —
    // in wizard mode `initialManifestJson` is undefined, so without this any
    // typing would compute a new manifest but never push it to the form.
    const editState = (updater: (prev: ManifestState) => ManifestState): void => {
        setHasContent(true)
        setState(updater)
    }
    const updateState = (patch: Partial<ManifestState>): void => editState((prev) => ({ ...prev, ...patch }))
    const updateStream = (index: number, patch: Partial<StreamForm>): void =>
        editState((prev) => ({
            ...prev,
            streams: prev.streams.map((stream, i) => (i === index ? { ...stream, ...patch } : stream)),
        }))
    const updatePaginator = (index: number, paginator: Paginator): void => updateStream(index, { paginator })
    const addStream = (): void => editState((prev) => ({ ...prev, streams: [...prev.streams, emptyStream()] }))
    const removeStream = (index: number): void =>
        editState((prev) => ({ ...prev, streams: prev.streams.filter((_, i) => i !== index) }))
    const addHeader = (): void => editState((prev) => ({ ...prev, headers: [...prev.headers, { key: '', value: '' }] }))
    const removeHeader = (index: number): void =>
        editState((prev) => ({ ...prev, headers: prev.headers.filter((_, i) => i !== index) }))
    const updateHeader = (index: number, patch: Partial<HeaderEntry>): void =>
        editState((prev) => ({
            ...prev,
            headers: prev.headers.map((header, i) => (i === index ? { ...header, ...patch } : header)),
        }))

    return (
        <div className="space-y-6">
            <LemonField.Pure label="Base URL" htmlFor="custom-source-base-url">
                <LemonInput
                    id="custom-source-base-url"
                    placeholder="https://api.example.com"
                    value={state.base_url}
                    onChange={(value) => updateState({ base_url: value })}
                />
                <p className="mt-1 text-xs text-secondary">
                    Must use <code>https://</code> on PostHog Cloud. Internal/private hostnames are rejected.
                </p>
            </LemonField.Pure>

            <AuthSection state={state} update={updateState} />

            <HeadersSection headers={state.headers} onAdd={addHeader} onRemove={removeHeader} onUpdate={updateHeader} />

            <LemonDivider />

            <div className="space-y-4">
                <div className="flex items-center justify-between">
                    <div>
                        <h4 className="mb-0">Streams</h4>
                        <p className="m-0 text-xs text-secondary">
                            Each stream becomes a table. PostHog fetches the endpoint, paginates, and writes rows.
                        </p>
                    </div>
                    <LemonButton type="secondary" icon={<IconPlus />} onClick={addStream}>
                        Add stream
                    </LemonButton>
                </div>
                {state.streams.map((stream, index) => (
                    <StreamCard
                        key={index}
                        index={index}
                        stream={stream}
                        canRemove={state.streams.length > 1}
                        onUpdate={(patch) => updateStream(index, patch)}
                        onUpdatePaginator={(paginator) => updatePaginator(index, paginator)}
                        onRemove={() => removeStream(index)}
                    />
                ))}
            </div>

            <details className="rounded border border-border p-3">
                <summary className="cursor-pointer text-xs text-secondary">Show generated manifest</summary>
                <LemonTextArea className="mt-2 font-mono text-xs" value={manifestJson} readOnly minRows={8} />
            </details>
        </div>
    )
}

function AuthSection({
    state,
    update,
}: {
    state: ManifestState
    update: (patch: Partial<ManifestState>) => void
}): JSX.Element {
    return (
        <div className="space-y-2">
            <LemonField.Pure label="Authentication">
                <LemonSelect
                    value={state.auth_type}
                    onChange={(value) => update({ auth_type: value as AuthType })}
                    options={AUTH_OPTIONS}
                />
            </LemonField.Pure>
            {state.auth_type === 'bearer' && (
                <LemonField.Pure label="Bearer token">
                    <LemonInput
                        type="password"
                        placeholder="ya29...."
                        value={state.auth_token}
                        onChange={(value) => update({ auth_token: value })}
                    />
                </LemonField.Pure>
            )}
            {state.auth_type === 'api_key' && (
                <div className="grid grid-cols-2 gap-2">
                    <LemonField.Pure label="Header name">
                        <LemonInput
                            placeholder="Authorization"
                            value={state.auth_api_key_name}
                            onChange={(value) => update({ auth_api_key_name: value })}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="API key">
                        <LemonInput
                            type="password"
                            placeholder="sk_live_…"
                            value={state.auth_api_key}
                            onChange={(value) => update({ auth_api_key: value })}
                        />
                    </LemonField.Pure>
                </div>
            )}
            {state.auth_type === 'http_basic' && (
                <div className="grid grid-cols-2 gap-2">
                    <LemonField.Pure label="Username">
                        <LemonInput
                            value={state.auth_username}
                            onChange={(value) => update({ auth_username: value })}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Password">
                        <LemonInput
                            type="password"
                            value={state.auth_password}
                            onChange={(value) => update({ auth_password: value })}
                        />
                    </LemonField.Pure>
                </div>
            )}
        </div>
    )
}

function HeadersSection({
    headers,
    onAdd,
    onRemove,
    onUpdate,
}: {
    headers: HeaderEntry[]
    onAdd: () => void
    onRemove: (index: number) => void
    onUpdate: (index: number, patch: Partial<HeaderEntry>) => void
}): JSX.Element {
    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between">
                <LemonField.Pure label="Default headers" />
                <LemonButton type="tertiary" size="small" icon={<IconPlus />} onClick={onAdd}>
                    Add header
                </LemonButton>
            </div>
            {headers.length === 0 ? (
                <p className="m-0 text-xs text-secondary">
                    No extra headers. Auth headers above are added automatically.
                </p>
            ) : (
                <div className="space-y-2">
                    {headers.map((header, index) => (
                        <div key={index} className="flex items-center gap-2">
                            <LemonInput
                                placeholder="Header name"
                                value={header.key}
                                onChange={(value) => onUpdate(index, { key: value })}
                            />
                            <LemonInput
                                placeholder="Header value"
                                value={header.value}
                                onChange={(value) => onUpdate(index, { value })}
                            />
                            <LemonButton type="tertiary" icon={<IconTrash />} onClick={() => onRemove(index)} />
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}

function StreamCard({
    index,
    stream,
    canRemove,
    onUpdate,
    onUpdatePaginator,
    onRemove,
}: {
    index: number
    stream: StreamForm
    canRemove: boolean
    onUpdate: (patch: Partial<StreamForm>) => void
    onUpdatePaginator: (paginator: Paginator) => void
    onRemove: () => void
}): JSX.Element {
    return (
        <div className="rounded border border-border p-3 space-y-3">
            <div className="flex items-center justify-between">
                <h5 className="mb-0">Stream {index + 1}</h5>
                {canRemove && (
                    <LemonButton type="tertiary" size="small" icon={<IconTrash />} onClick={onRemove}>
                        Remove
                    </LemonButton>
                )}
            </div>
            <div className="grid grid-cols-2 gap-2">
                <LemonField.Pure label="Stream name">
                    <LemonInput
                        placeholder="users"
                        value={stream.name}
                        onChange={(value) => onUpdate({ name: value })}
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Primary key">
                    <LemonInput
                        placeholder="id"
                        value={stream.primary_key}
                        onChange={(value) => onUpdate({ primary_key: value })}
                    />
                </LemonField.Pure>
            </div>
            <div className="grid grid-cols-2 gap-2">
                <LemonField.Pure label="Path">
                    <LemonInput
                        placeholder="/v1/users"
                        value={stream.path}
                        onChange={(value) => onUpdate({ path: value })}
                    />
                </LemonField.Pure>
                <LemonField.Pure label="HTTP method">
                    <LemonSelect
                        value={stream.method}
                        onChange={(value) => onUpdate({ method: value as 'GET' | 'POST' })}
                        options={[
                            { value: 'GET', label: 'GET' },
                            { value: 'POST', label: 'POST' },
                        ]}
                    />
                </LemonField.Pure>
            </div>
            <LemonField.Pure label="Records JSONPath">
                <LemonInput
                    placeholder="data"
                    value={stream.data_selector}
                    onChange={(value) => onUpdate({ data_selector: value })}
                />
                <p className="m-0 mt-1 text-xs text-secondary">
                    JSONPath that points at the array of rows in each response (e.g. <code>data</code>,{' '}
                    <code>items</code>, <code>results.data</code>).
                </p>
            </LemonField.Pure>
            <PaginatorSection paginator={stream.paginator} onUpdate={onUpdatePaginator} />
            <IncrementalSection stream={stream} onUpdate={onUpdate} />
        </div>
    )
}

function PaginatorSection({
    paginator,
    onUpdate,
}: {
    paginator: Paginator
    onUpdate: (paginator: Paginator) => void
}): JSX.Element {
    const switchType = (type: Paginator['type']): void => {
        switch (type) {
            case 'single_page':
                onUpdate({ type })
                return
            case 'json_response':
                onUpdate({ type, next_url_path: 'links.next' })
                return
            case 'cursor':
                onUpdate({ type, cursor_path: 'meta.next_cursor', cursor_param: 'cursor' })
                return
            case 'offset':
                onUpdate({ type, limit: 100, offset_param: 'offset', limit_param: 'limit' })
                return
            case 'page_number':
                onUpdate({ type, page_param: 'page', initial_page: 1 })
                return
            case 'header_link':
                onUpdate({ type, links_next_key: 'next' })
                return
        }
    }

    return (
        <div className="space-y-2">
            <LemonField.Pure label="Paginator">
                <LemonSelect
                    value={paginator.type}
                    onChange={(value) => switchType(value)}
                    options={PAGINATOR_OPTIONS}
                />
            </LemonField.Pure>
            {paginator.type === 'json_response' && (
                <LemonField.Pure label="Next-URL JSONPath">
                    <LemonInput
                        placeholder="links.next"
                        value={paginator.next_url_path ?? ''}
                        onChange={(value) => onUpdate({ ...paginator, next_url_path: value })}
                    />
                </LemonField.Pure>
            )}
            {paginator.type === 'cursor' && (
                <div className="grid grid-cols-2 gap-2">
                    <LemonField.Pure label="Cursor JSONPath">
                        <LemonInput
                            placeholder="meta.next_cursor"
                            value={paginator.cursor_path ?? ''}
                            onChange={(value) => onUpdate({ ...paginator, cursor_path: value })}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Cursor query param">
                        <LemonInput
                            placeholder="cursor"
                            value={paginator.cursor_param ?? ''}
                            onChange={(value) => onUpdate({ ...paginator, cursor_param: value })}
                        />
                    </LemonField.Pure>
                </div>
            )}
            {paginator.type === 'offset' && (
                <div className="grid grid-cols-3 gap-2">
                    <LemonField.Pure label="Page size">
                        <LemonInput
                            type="number"
                            value={String(paginator.limit ?? 100)}
                            onChange={(value) => onUpdate({ ...paginator, limit: Number(value) || 100 })}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Offset param">
                        <LemonInput
                            placeholder="offset"
                            value={paginator.offset_param ?? ''}
                            onChange={(value) => onUpdate({ ...paginator, offset_param: value })}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Limit param">
                        <LemonInput
                            placeholder="limit"
                            value={paginator.limit_param ?? ''}
                            onChange={(value) => onUpdate({ ...paginator, limit_param: value })}
                        />
                    </LemonField.Pure>
                </div>
            )}
            {paginator.type === 'page_number' && (
                <div className="grid grid-cols-2 gap-2">
                    <LemonField.Pure label="Page query param">
                        <LemonInput
                            placeholder="page"
                            value={paginator.page_param ?? ''}
                            onChange={(value) => onUpdate({ ...paginator, page_param: value })}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Initial page">
                        <LemonInput
                            type="number"
                            value={String(paginator.initial_page ?? 1)}
                            onChange={(value) => onUpdate({ ...paginator, initial_page: Number(value) || 1 })}
                        />
                    </LemonField.Pure>
                </div>
            )}
            {paginator.type === 'header_link' && (
                <LemonField.Pure label="rel= key in Link header">
                    <LemonInput
                        placeholder="next"
                        value={paginator.links_next_key ?? ''}
                        onChange={(value) => onUpdate({ ...paginator, links_next_key: value })}
                    />
                </LemonField.Pure>
            )}
        </div>
    )
}

function IncrementalSection({
    stream,
    onUpdate,
}: {
    stream: StreamForm
    onUpdate: (patch: Partial<StreamForm>) => void
}): JSX.Element {
    return (
        <div className="rounded border border-border p-3 space-y-2">
            <label className="flex items-center gap-2 cursor-pointer">
                <input
                    type="checkbox"
                    checked={stream.incremental_enabled}
                    onChange={(event) => onUpdate({ incremental_enabled: event.target.checked })}
                />
                <span>Enable incremental sync</span>
            </label>
            {stream.incremental_enabled && (
                <div className="grid grid-cols-2 gap-2">
                    <LemonField.Pure label="Cursor JSONPath">
                        <LemonInput
                            placeholder="updated_at"
                            value={stream.cursor_path}
                            onChange={(value) => onUpdate({ cursor_path: value })}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Cursor query param">
                        <LemonInput
                            placeholder="since"
                            value={stream.start_param}
                            onChange={(value) => onUpdate({ start_param: value })}
                        />
                    </LemonField.Pure>
                </div>
            )}
        </div>
    )
}
