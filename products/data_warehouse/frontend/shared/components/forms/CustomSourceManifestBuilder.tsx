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
    eligibleParentTables,
    EMPTY_PARENT_FIELDS,
    type HeaderEntry,
    type ManifestState,
    type Paginator,
    PAGINATOR_DEFAULTS,
    PAGINATOR_TYPES,
    type PaginatorType,
    SORT_MODES,
    type SortMode,
    type TableForm,
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

// The only cursor types `datetime_format` applies to — the backend ignores it for any other type.
const DATE_LIKE_CURSOR_TYPES: readonly CursorType[] = ['datetime', 'date', 'timestamp']

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
        updateTable,
        updatePaginator,
        addTable,
        removeTable,
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
                        <h4 className="mb-0">Tables</h4>
                        <p className="m-0 text-xs text-secondary">
                            Each table maps to one endpoint. PostHog fetches it, paginates, and writes the rows.
                        </p>
                    </div>
                    <LemonButton type="secondary" icon={<IconPlus />} onClick={addTable}>
                        Add table
                    </LemonButton>
                </div>
                {manifestState.tables.map((table, index) => (
                    <TableCard
                        key={table.id}
                        index={index}
                        table={table}
                        canRemove={manifestState.tables.length > 1}
                        parentOptions={eligibleParentTables(manifestState.tables, index)}
                        onUpdate={(patch) => updateTable(index, patch)}
                        onUpdatePaginator={(paginator) => updatePaginator(index, paginator)}
                        onRemove={() => removeTable(index)}
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

function TableCard({
    index,
    table,
    canRemove,
    parentOptions,
    onUpdate,
    onUpdatePaginator,
    onRemove,
}: {
    index: number
    table: TableForm
    canRemove: boolean
    parentOptions: string[]
    onUpdate: (patch: Partial<TableForm>) => void
    onUpdatePaginator: (paginator: Paginator) => void
    onRemove: () => void
}): JSX.Element {
    return (
        <div className="rounded border border-border p-3 space-y-3">
            <div className="flex items-center justify-between">
                <h5 className="mb-0">Table {index + 1}</h5>
                {canRemove && (
                    <LemonButton type="tertiary" size="small" icon={<IconTrash />} onClick={onRemove}>
                        Remove
                    </LemonButton>
                )}
            </div>
            <div className="grid grid-cols-2 gap-2">
                <LemonField.Pure label="Table name">
                    <LemonInput
                        placeholder="users"
                        value={table.name}
                        onChange={(value) => onUpdate({ name: value })}
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Primary key">
                    <LemonInput
                        placeholder="id"
                        value={table.primary_key}
                        onChange={(value) => onUpdate({ primary_key: value })}
                    />
                </LemonField.Pure>
            </div>
            <div className="grid grid-cols-2 gap-2">
                <LemonField.Pure label="Path">
                    <LemonInput
                        placeholder="/v1/users"
                        value={table.path}
                        onChange={(value) => onUpdate({ path: value })}
                    />
                </LemonField.Pure>
                <LemonField.Pure label="HTTP method">
                    <LemonSelect
                        value={table.method}
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
                    value={table.data_selector}
                    onChange={(value) => onUpdate({ data_selector: value })}
                />
                <p className="m-0 mt-1 text-xs text-secondary">
                    JSONPath that points at the array of rows in each response (e.g. <code>data</code>,{' '}
                    <code>items</code>, <code>results.data</code>).
                </p>
            </LemonField.Pure>
            {/* Only show the dependency section when there's an eligible parent to
                pick, or an existing dependency to edit / warn about (a stale parent
                from raw-authored JSON still needs its warning). A single-table
                manifest has neither, so the section would just be an inert box. */}
            {(parentOptions.length > 0 || table.parent_table.trim().length > 0) && (
                <ParentSection table={table} parentOptions={parentOptions} onUpdate={onUpdate} />
            )}
            <PaginatorSection paginator={table.paginator} onUpdate={onUpdatePaginator} />
            <IncrementalSection table={table} onUpdate={onUpdate} />
        </div>
    )
}

function ParentSection({
    table,
    parentOptions,
    onUpdate,
}: {
    table: TableForm
    parentOptions: string[]
    onUpdate: (patch: Partial<TableForm>) => void
}): JSX.Element {
    const hasParent = table.parent_table.trim().length > 0
    const pathParam = table.parent_path_param.trim()
    const parentField = table.parent_resolve_field.trim()
    // A parent name can go stale when the manifest was authored elsewhere (raw
    // JSON) — the select would render the raw value with no visible error, and
    // saving fails with an engine message that doesn't point here.
    const parentMissing = hasParent && !parentOptions.includes(table.parent_table)
    // The REST engine can only inject a resolved value into the URL path, so the
    // path must contain the placeholder — warn early instead of failing at sync.
    const pathMissingPlaceholder = hasParent && pathParam.length > 0 && !table.path.includes(`{${pathParam}}`)
    return (
        <div className="rounded border border-border p-3 space-y-2">
            <LemonField.Pure label="Depends on parent table">
                <LemonSelect
                    value={hasParent ? table.parent_table : ''}
                    onChange={(value) =>
                        value ? onUpdate({ parent_table: value }) : onUpdate({ ...EMPTY_PARENT_FIELDS })
                    }
                    options={[
                        { value: '', label: 'None (top-level table)' },
                        ...parentOptions.map((name) => ({ value: name, label: name })),
                    ]}
                />
            </LemonField.Pure>
            {hasParent && (
                <>
                    <p className="m-0 text-xs text-secondary">
                        PostHog fetches the parent table first, then calls this table once per parent row — binding the
                        chosen parent field into the path placeholder (e.g. <code>/forms/{'{form_id}'}/responses</code>
                        ).
                    </p>
                    <div className="grid grid-cols-2 gap-2">
                        <LemonField.Pure label="Parent field">
                            <LemonInput
                                placeholder="id"
                                value={table.parent_resolve_field}
                                onChange={(value) => onUpdate({ parent_resolve_field: value })}
                            />
                        </LemonField.Pure>
                        <LemonField.Pure label="Path placeholder">
                            <LemonInput
                                placeholder="form_id"
                                value={table.parent_path_param}
                                onChange={(value) => onUpdate({ parent_path_param: value })}
                            />
                        </LemonField.Pure>
                    </div>
                    <LemonField.Pure label="Include parent fields">
                        <LemonInput
                            placeholder="id, name"
                            value={table.include_from_parent}
                            onChange={(value) => onUpdate({ include_from_parent: value })}
                        />
                        <p className="m-0 mt-1 text-xs text-secondary">
                            Optional comma-separated parent fields copied onto each row, as{' '}
                            <code>_{table.parent_table || 'parent'}_&lt;field&gt;</code>.
                        </p>
                    </LemonField.Pure>
                </>
            )}
            {/* One persistently-mounted live region so screen readers announce
                validation messages as they appear — a region that enters the DOM
                already populated (e.g. mounted inside the hasParent gate) is
                skipped by several readers. empty:hidden keeps it from adding
                spacing when there's nothing to say. */}
            <div aria-live="polite" className="empty:hidden space-y-2">
                {parentMissing && (
                    <p className="m-0 text-xs text-danger">
                        Table <code>{table.parent_table}</code> doesn't exist or can't be this table's parent — pick
                        another parent or set to none.
                    </p>
                )}
                {hasParent && !parentField && (
                    <p className="m-0 text-xs text-danger">
                        Set the parent field — the dependency is incomplete without it and saving fails.
                    </p>
                )}
                {hasParent && !pathParam && (
                    <p className="m-0 text-xs text-danger">
                        Set the path placeholder — the dependency is incomplete without it and saving fails.
                    </p>
                )}
                {pathMissingPlaceholder && (
                    <p className="m-0 text-xs text-danger">
                        Add <code>{`{${pathParam}}`}</code> to the path above — the parent field is injected there, and
                        the sync fails without it.
                    </p>
                )}
            </div>
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
    table,
    onUpdate,
}: {
    table: TableForm
    onUpdate: (patch: Partial<TableForm>) => void
}): JSX.Element {
    return (
        <div className="rounded border border-border p-3 space-y-2">
            <LemonCheckbox
                checked={table.incremental_enabled}
                onChange={(checked) => onUpdate({ incremental_enabled: checked })}
                label="Enable incremental sync"
            />
            {table.incremental_enabled && (
                <>
                    <div className="grid grid-cols-2 gap-2">
                        <LemonField.Pure label="Cursor JSONPath">
                            <LemonInput
                                placeholder="updated_at"
                                value={table.cursor_path}
                                onChange={(value) => onUpdate({ cursor_path: value })}
                            />
                        </LemonField.Pure>
                        <LemonField.Pure label="Cursor query param">
                            <LemonInput
                                placeholder="since"
                                value={table.start_param}
                                onChange={(value) => onUpdate({ start_param: value })}
                            />
                        </LemonField.Pure>
                    </div>
                    {!table.cursor_path.trim() && (
                        <p className="m-0 text-xs text-danger">
                            Set a cursor JSONPath — otherwise incremental sync is ignored and the table does a full
                            refresh every run.
                        </p>
                    )}
                    <div className="grid grid-cols-2 gap-2">
                        <LemonField.Pure label="Cursor type">
                            <LemonSelect
                                value={table.cursor_type}
                                onChange={(value) => onUpdate({ cursor_type: value as CursorType })}
                                options={CURSOR_TYPE_OPTIONS}
                            />
                        </LemonField.Pure>
                        <LemonField.Pure label="Upstream row order">
                            <LemonSelect
                                value={table.sort_mode}
                                onChange={(value) => onUpdate({ sort_mode: value as SortMode })}
                                options={SORT_MODE_OPTIONS}
                                disabledReason={
                                    table.parent_table.trim()
                                        ? 'Tables with a parent always defer the incremental cursor commit to the end of the run — rows arrive grouped by parent, not in cursor order.'
                                        : undefined
                                }
                            />
                        </LemonField.Pure>
                    </div>
                    <p className="m-0 text-xs text-secondary">
                        Pick "Descending" when the API returns newest rows first — otherwise a resumed sync may skip
                        rows.
                    </p>
                    {DATE_LIKE_CURSOR_TYPES.includes(table.cursor_type) && (
                        <LemonField.Pure label="Datetime format">
                            <LemonInput
                                placeholder="%Y-%m-%dT%H:%M:%SZ"
                                value={table.datetime_format}
                                onChange={(value) => onUpdate({ datetime_format: value })}
                            />
                            <p className="m-0 mt-1 text-xs text-secondary">
                                strftime pattern for the watermark sent to the API (e.g. <code>%Y-%m-%dT%H:%M:%SZ</code>
                                , <code>%s</code> for unix). Leave blank for ISO-8601.
                            </p>
                        </LemonField.Pure>
                    )}
                </>
            )}
        </div>
    )
}
