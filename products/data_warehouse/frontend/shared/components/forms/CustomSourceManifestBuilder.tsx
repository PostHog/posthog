import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDivider, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet/CodeSnippet'
import { LemonField } from 'lib/lemon-ui/LemonField'

import {
    API_KEY_LOCATIONS,
    type ApiKeyLocation,
    AUTH_TYPES,
    type AuthType,
    CURSOR_TYPES,
    type CursorType,
    type HeaderEntry,
    type ManifestState,
    type Paginator,
    PAGINATOR_DEFAULTS,
    PAGINATOR_TYPES,
    type PaginatorType,
    SORT_MODES,
    type SortMode,
    type StreamForm,
} from './customSourceManifest'
import {
    customSourceManifestBuilderLogic,
    type CustomSourceManifestBuilderLogicProps,
} from './customSourceManifestBuilderLogic'

// Option lists derive their value set from the single-source `as const` tuples in
// customSourceManifest.ts; only the labels live here, so the allowed values can't
// drift between the type, the parser, and these selects.
const PAGINATOR_LABELS: Record<PaginatorType, string> = {
    single_page: 'Single page (no pagination)',
    json_response: 'JSON body next-URL',
    cursor: 'Cursor in JSON body',
    offset: 'Offset / limit query params',
    page_number: 'Page number query param',
    header_link: 'Link header (RFC 5988)',
}
const PAGINATOR_OPTIONS = PAGINATOR_TYPES.map((value) => ({ value, label: PAGINATOR_LABELS[value] }))

const AUTH_LABELS: Record<AuthType, string> = {
    none: 'No auth',
    bearer: 'Bearer token',
    api_key: 'API key',
    http_basic: 'HTTP basic auth',
}
const AUTH_OPTIONS = AUTH_TYPES.map((value) => ({ value, label: AUTH_LABELS[value] }))

const API_KEY_LOCATION_LABELS: Record<ApiKeyLocation, string> = {
    header: 'Header',
    query: 'Query parameter',
    cookie: 'Cookie',
}
const API_KEY_LOCATION_OPTIONS = API_KEY_LOCATIONS.map((value) => ({ value, label: API_KEY_LOCATION_LABELS[value] }))

const CURSOR_TYPE_LABELS: Record<CursorType, string> = {
    datetime: 'Datetime',
    date: 'Date',
    timestamp: 'Timestamp (epoch)',
    integer: 'Integer',
}
const CURSOR_TYPE_OPTIONS = CURSOR_TYPES.map((value) => ({ value, label: CURSOR_TYPE_LABELS[value] }))

const SORT_MODE_LABELS: Record<SortMode, string> = {
    asc: 'Ascending (oldest first)',
    desc: 'Descending (newest first)',
}
const SORT_MODE_OPTIONS = SORT_MODES.map((value) => ({ value, label: SORT_MODE_LABELS[value] }))

/**
 * Visual builder for the Custom REST source's manifest. State and the
 * outer-form sync live in `customSourceManifestBuilderLogic`; this component
 * only renders the form and dispatches actions.
 */
export function CustomSourceManifestBuilder({
    initialManifestJson,
    setValue,
}: CustomSourceManifestBuilderLogicProps): JSX.Element {
    const logic = customSourceManifestBuilderLogic({ initialManifestJson, setValue })
    const { manifestState, manifestJson, manifestPreviewOpen } = useValues(logic)
    const {
        updateState,
        updateStream,
        updatePaginator,
        addStream,
        removeStream,
        addHeader,
        removeHeader,
        updateHeader,
        setManifestPreviewOpen,
    } = useActions(logic)

    return (
        <div className="space-y-6">
            <LemonField.Pure label="Base URL" htmlFor="custom-source-base-url">
                <LemonInput
                    id="custom-source-base-url"
                    placeholder="https://api.example.com"
                    value={manifestState.base_url}
                    onChange={(value) => updateState({ base_url: value })}
                />
            </LemonField.Pure>

            <AuthSection state={manifestState} update={updateState} />

            <HeadersSection
                headers={manifestState.headers}
                onAdd={addHeader}
                onRemove={removeHeader}
                onUpdate={updateHeader}
            />

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
                {manifestState.streams.map((stream, index) => (
                    <StreamCard
                        key={stream.id}
                        index={index}
                        stream={stream}
                        canRemove={manifestState.streams.length > 1}
                        parentOptions={manifestState.streams
                            .filter((other, otherIndex) => otherIndex !== index && other.name.trim().length > 0)
                            .map((other) => ({ value: other.name, label: other.name }))}
                        onUpdate={(patch) => updateStream(index, patch)}
                        onUpdatePaginator={(paginator) => updatePaginator(index, paginator)}
                        onRemove={() => removeStream(index)}
                    />
                ))}
            </div>

            <details
                className="rounded border border-border p-3"
                open={manifestPreviewOpen}
                onToggle={(e) => setManifestPreviewOpen((e.target as HTMLDetailsElement).open)}
            >
                <summary className="cursor-pointer text-xs text-secondary">Show generated manifest</summary>
                {/* Only render (and syntax-highlight) the snippet while expanded — otherwise
                    lowlight re-runs over the whole manifest on every keystroke even when collapsed. */}
                {manifestPreviewOpen && (
                    <CodeSnippet language={Language.JSON} className="mt-2 text-xs" wrap maxLinesWithoutExpansion={20}>
                        {manifestJson}
                    </CodeSnippet>
                )}
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
                        autoComplete="off"
                        placeholder="ya29...."
                        value={state.auth_token}
                        onChange={(value) => update({ auth_token: value })}
                    />
                </LemonField.Pure>
            )}
            {state.auth_type === 'api_key' && (
                <div className="grid grid-cols-3 gap-2">
                    <LemonField.Pure label="Location">
                        <LemonSelect
                            value={state.auth_api_key_location}
                            onChange={(value) => update({ auth_api_key_location: value as ApiKeyLocation })}
                            options={API_KEY_LOCATION_OPTIONS}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure
                        label={state.auth_api_key_location === 'header' ? 'Header name' : 'Parameter name'}
                    >
                        <LemonInput
                            placeholder={state.auth_api_key_location === 'header' ? 'Authorization' : 'api_key'}
                            value={state.auth_api_key_name}
                            onChange={(value) => update({ auth_api_key_name: value })}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="API key">
                        <LemonInput
                            type="password"
                            autoComplete="off"
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
                            autoComplete="off"
                            value={state.auth_username}
                            onChange={(value) => update({ auth_username: value })}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Password">
                        <LemonInput
                            type="password"
                            autoComplete="off"
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
                <span className="text-sm font-medium">Default headers</span>
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
                        <div key={header.id} className="flex items-center gap-2">
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
                            <LemonButton
                                type="tertiary"
                                icon={<IconTrash />}
                                tooltip="Remove header"
                                onClick={() => onRemove(index)}
                            />
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
    parentOptions,
    onUpdate,
    onUpdatePaginator,
    onRemove,
}: {
    index: number
    stream: StreamForm
    canRemove: boolean
    parentOptions: { value: string; label: string }[]
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
            <ParentSection stream={stream} parentOptions={parentOptions} onUpdate={onUpdate} />
            <PaginatorSection paginator={stream.paginator} onUpdate={onUpdatePaginator} />
            <IncrementalSection stream={stream} onUpdate={onUpdate} />
        </div>
    )
}

function ParentSection({
    stream,
    parentOptions,
    onUpdate,
}: {
    stream: StreamForm
    parentOptions: { value: string; label: string }[]
    onUpdate: (patch: Partial<StreamForm>) => void
}): JSX.Element {
    const hasParent = stream.parent_stream.trim().length > 0
    const pathParam = stream.parent_path_param.trim()
    // The REST engine can only inject a resolved value into the URL path, so the
    // path must contain the placeholder — warn early instead of failing at sync.
    const pathMissingPlaceholder = hasParent && pathParam.length > 0 && !stream.path.includes(`{${pathParam}}`)
    return (
        <div className="rounded border border-border p-3 space-y-2">
            <LemonField.Pure label="Depends on parent stream">
                <LemonSelect
                    value={hasParent ? stream.parent_stream : ''}
                    onChange={(value) =>
                        value
                            ? onUpdate({ parent_stream: value })
                            : onUpdate({
                                  parent_stream: '',
                                  parent_resolve_field: '',
                                  parent_path_param: '',
                                  include_from_parent: '',
                              })
                    }
                    options={[{ value: '', label: 'None (top-level stream)' }, ...parentOptions]}
                />
            </LemonField.Pure>
            {hasParent && (
                <>
                    <p className="m-0 text-xs text-secondary">
                        PostHog fetches the parent stream first, then calls this stream once per parent row — binding
                        the chosen parent field into the path placeholder (e.g.{' '}
                        <code>/forms/{'{form_id}'}/responses</code>).
                    </p>
                    <div className="grid grid-cols-2 gap-2">
                        <LemonField.Pure label="Parent field">
                            <LemonInput
                                placeholder="id"
                                value={stream.parent_resolve_field}
                                onChange={(value) => onUpdate({ parent_resolve_field: value })}
                            />
                        </LemonField.Pure>
                        <LemonField.Pure label="Path placeholder">
                            <LemonInput
                                placeholder="form_id"
                                value={stream.parent_path_param}
                                onChange={(value) => onUpdate({ parent_path_param: value })}
                            />
                        </LemonField.Pure>
                    </div>
                    {pathMissingPlaceholder && (
                        <p className="m-0 text-xs text-danger">
                            Add <code>{`{${pathParam}}`}</code> to the path above — the parent field is injected there,
                            and the sync fails without it.
                        </p>
                    )}
                    <LemonField.Pure label="Include parent fields">
                        <LemonInput
                            placeholder="id, name"
                            value={stream.include_from_parent}
                            onChange={(value) => onUpdate({ include_from_parent: value })}
                        />
                        <p className="m-0 mt-1 text-xs text-secondary">
                            Optional comma-separated parent fields copied onto each row, as{' '}
                            <code>_{stream.parent_stream || 'parent'}_&lt;field&gt;</code>.
                        </p>
                    </LemonField.Pure>
                </>
            )}
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
                onUpdate({ type, ...PAGINATOR_DEFAULTS.json_response })
                return
            case 'cursor':
                onUpdate({ type, ...PAGINATOR_DEFAULTS.cursor })
                return
            case 'offset':
                onUpdate({ type, ...PAGINATOR_DEFAULTS.offset })
                return
            case 'page_number':
                onUpdate({ type, ...PAGINATOR_DEFAULTS.page_number })
                return
            case 'header_link':
                onUpdate({ type, ...PAGINATOR_DEFAULTS.header_link })
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
                        placeholder={PAGINATOR_DEFAULTS.json_response.next_url_path}
                        value={paginator.next_url_path ?? ''}
                        onChange={(value) => onUpdate({ ...paginator, next_url_path: value })}
                    />
                </LemonField.Pure>
            )}
            {paginator.type === 'cursor' && (
                <div className="grid grid-cols-2 gap-2">
                    <LemonField.Pure label="Cursor JSONPath">
                        <LemonInput
                            placeholder={PAGINATOR_DEFAULTS.cursor.cursor_path}
                            value={paginator.cursor_path ?? ''}
                            onChange={(value) => onUpdate({ ...paginator, cursor_path: value })}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Cursor query param">
                        <LemonInput
                            placeholder={PAGINATOR_DEFAULTS.cursor.cursor_param}
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
                            value={paginator.limit ?? PAGINATOR_DEFAULTS.offset.limit}
                            onChange={(value) =>
                                onUpdate({ ...paginator, limit: value ?? PAGINATOR_DEFAULTS.offset.limit })
                            }
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Offset param">
                        <LemonInput
                            placeholder={PAGINATOR_DEFAULTS.offset.offset_param}
                            value={paginator.offset_param ?? ''}
                            onChange={(value) => onUpdate({ ...paginator, offset_param: value })}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Limit param">
                        <LemonInput
                            placeholder={PAGINATOR_DEFAULTS.offset.limit_param}
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
                            placeholder={PAGINATOR_DEFAULTS.page_number.page_param}
                            value={paginator.page_param ?? ''}
                            onChange={(value) => onUpdate({ ...paginator, page_param: value })}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Initial page">
                        <LemonInput
                            type="number"
                            value={paginator.base_page ?? PAGINATOR_DEFAULTS.page_number.base_page}
                            onChange={(value) =>
                                onUpdate({ ...paginator, base_page: value ?? PAGINATOR_DEFAULTS.page_number.base_page })
                            }
                        />
                    </LemonField.Pure>
                </div>
            )}
            {paginator.type === 'header_link' && (
                <LemonField.Pure label="rel= key in Link header">
                    <LemonInput
                        placeholder={PAGINATOR_DEFAULTS.header_link.links_next_key}
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
            <LemonCheckbox
                checked={stream.incremental_enabled}
                onChange={(checked) => onUpdate({ incremental_enabled: checked })}
                label="Enable incremental sync"
            />
            {stream.incremental_enabled && (
                <>
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
                    {!stream.cursor_path.trim() && (
                        <p className="m-0 text-xs text-danger">
                            Set a cursor JSONPath — otherwise incremental sync is ignored and the stream does a full
                            refresh every run.
                        </p>
                    )}
                    <div className="grid grid-cols-2 gap-2">
                        <LemonField.Pure label="Cursor type">
                            <LemonSelect
                                value={stream.cursor_type}
                                onChange={(value) => onUpdate({ cursor_type: value as CursorType })}
                                options={CURSOR_TYPE_OPTIONS}
                            />
                        </LemonField.Pure>
                        <LemonField.Pure label="Upstream row order">
                            <LemonSelect
                                value={stream.sort_mode}
                                onChange={(value) => onUpdate({ sort_mode: value as SortMode })}
                                options={SORT_MODE_OPTIONS}
                            />
                        </LemonField.Pure>
                    </div>
                    <p className="m-0 text-xs text-secondary">
                        Pick "Descending" when the API returns newest rows first — otherwise a resumed sync may skip
                        rows.
                    </p>
                </>
            )}
        </div>
    )
}
