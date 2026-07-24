import {
    buildManifest,
    eligibleParentTables,
    extractAuthSecrets,
    ManifestState,
    parseManifestIntoState,
    removeTableFromList,
    TableForm,
    updateTableInList,
    visibleAuthTypes,
} from '../customSourceManifest'

const baseState = (): ManifestState => ({
    base_url: 'https://api.example.com',
    auth_type: 'bearer',
    auth_token: 'tok_123',
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
    tables: [
        {
            id: 'table-base',
            name: 'users',
            path: '/v1/users',
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
            parent_table: '',
            parent_resolve_field: '',
            parent_path_param: '',
            include_from_parent: '',
            passthrough_params: {},
        },
    ],
})

describe('buildManifest', () => {
    it('emits client.auth for bearer with no inline credential', () => {
        const manifest = buildManifest(baseState()) as any
        expect(manifest.client.auth).toEqual({ type: 'bearer' })
        expect(manifest.client.auth.token).toBeUndefined()
    })

    it('emits client.auth with api_key header location but no key value', () => {
        const state = baseState()
        state.auth_type = 'api_key'
        state.auth_api_key = 'sk_test'
        state.auth_api_key_name = 'X-API-Key'
        const manifest = buildManifest(state) as any
        expect(manifest.client.auth).toEqual({ type: 'api_key', name: 'X-API-Key', location: 'header' })
        expect(manifest.client.auth.api_key).toBeUndefined()
    })

    it.each(['header', 'query', 'cookie'] as const)('threads api_key location=%s into client.auth', (location) => {
        const state = baseState()
        state.auth_type = 'api_key'
        state.auth_api_key_location = location
        state.auth_api_key_name = 'key'
        const manifest = buildManifest(state) as any
        expect(manifest.client.auth.location).toBe(location)
    })

    it('emits http_basic auth with username but no password', () => {
        const state = baseState()
        state.auth_type = 'http_basic'
        state.auth_username = 'alice'
        state.auth_password = 'hunter2'
        const manifest = buildManifest(state) as any
        expect(manifest.client.auth).toEqual({ type: 'http_basic', username: 'alice' })
        expect(manifest.client.auth.password).toBeUndefined()
    })

    it("omits client.auth when 'none' is selected", () => {
        const state = baseState()
        state.auth_type = 'none'
        const manifest = buildManifest(state) as any
        expect(manifest.client.auth).toBeUndefined()
    })

    it('serializes non-empty headers into client.headers as a map', () => {
        const state = baseState()
        state.headers = [
            { id: 'h1', key: 'X-Workspace', value: 'acme' },
            { id: 'h2', key: '', value: 'ignored' },
            { id: 'h3', key: '  ', value: 'also ignored' },
        ]
        const manifest = buildManifest(state) as any
        expect(manifest.client.headers).toEqual({ 'X-Workspace': 'acme' })
    })

    it('omits client.headers entirely when no real entries are present', () => {
        const state = baseState()
        state.headers = [{ id: 'h1', key: '', value: 'whatever' }]
        const manifest = buildManifest(state) as any
        expect('headers' in manifest.client).toBe(false)
    })

    it('splits a comma-separated primary_key into a list when multi-column', () => {
        const state = baseState()
        state.tables[0].primary_key = 'user_id, page_url, day'
        const manifest = buildManifest(state) as any
        expect(manifest.resources[0].primary_key).toEqual(['user_id', 'page_url', 'day'])
    })

    it('keeps a single primary_key as a string', () => {
        const manifest = buildManifest(baseState()) as any
        expect(manifest.resources[0].primary_key).toEqual('id')
    })

    it.each(['', '   ', ' , '])('falls back to id when primary_key is cleared (%p)', (cleared) => {
        const state = baseState()
        state.tables[0].primary_key = cleared
        const manifest = buildManifest(state) as any
        expect(manifest.resources[0].primary_key).toEqual('id')
    })

    it("only sets endpoint.method when the table isn't GET", () => {
        const get = buildManifest(baseState()) as any
        expect('method' in get.resources[0].endpoint).toBe(false)

        const state = baseState()
        state.tables[0].method = 'POST'
        const post = buildManifest(state) as any
        expect(post.resources[0].endpoint.method).toBe('POST')
    })

    it('serializes paginator-specific fields per paginator type', () => {
        const offsetState = baseState()
        offsetState.tables[0].paginator = { type: 'offset', limit: 50, offset_param: 'o', limit_param: 'l' }
        const offsetManifest = buildManifest(offsetState) as any
        expect(offsetManifest.resources[0].endpoint.paginator).toEqual({
            type: 'offset',
            limit: 50,
            offset_param: 'o',
            limit_param: 'l',
        })

        const pageState = baseState()
        pageState.tables[0].paginator = { type: 'page_number', page_param: 'p', base_page: 0 }
        const pageManifest = buildManifest(pageState) as any
        expect(pageManifest.resources[0].endpoint.paginator).toEqual({
            type: 'page_number',
            page_param: 'p',
            base_page: 0,
        })
    })

    it('fills paginator defaults when fields are left blank', () => {
        const state = baseState()
        state.tables[0].paginator = { type: 'cursor' }
        const manifest = buildManifest(state) as any
        expect(manifest.resources[0].endpoint.paginator).toEqual({
            type: 'cursor',
            cursor_path: 'meta.next_cursor',
            cursor_param: 'cursor',
        })
    })

    it('serializes json_response with an explicit and a default next_url_path', () => {
        const explicit = baseState()
        explicit.tables[0].paginator = { type: 'json_response', next_url_path: 'paging.next' }
        expect((buildManifest(explicit) as any).resources[0].endpoint.paginator).toEqual({
            type: 'json_response',
            next_url_path: 'paging.next',
        })

        const blank = baseState()
        blank.tables[0].paginator = { type: 'json_response' }
        expect((buildManifest(blank) as any).resources[0].endpoint.paginator).toEqual({
            type: 'json_response',
            next_url_path: 'links.next',
        })
    })

    it('serializes header_link with an explicit and a default links_next_key', () => {
        const explicit = baseState()
        explicit.tables[0].paginator = { type: 'header_link', links_next_key: 'successor' }
        expect((buildManifest(explicit) as any).resources[0].endpoint.paginator).toEqual({
            type: 'header_link',
            links_next_key: 'successor',
        })

        const blank = baseState()
        blank.tables[0].paginator = { type: 'header_link' }
        expect((buildManifest(blank) as any).resources[0].endpoint.paginator).toEqual({
            type: 'header_link',
            links_next_key: 'next',
        })
    })

    it('emits endpoint.incremental only when enabled AND cursor_path is set', () => {
        const state = baseState()
        state.tables[0].incremental_enabled = true
        state.tables[0].cursor_path = 'updated_at'
        const manifest = buildManifest(state) as any
        expect(manifest.resources[0].endpoint.incremental).toEqual({
            cursor_path: 'updated_at',
            start_param: 'updated_at',
        })

        state.tables[0].start_param = 'since'
        const overriddenStart = buildManifest(state) as any
        expect(overriddenStart.resources[0].endpoint.incremental.start_param).toBe('since')

        state.tables[0].cursor_path = ''
        const noCursor = buildManifest(state) as any
        expect('incremental' in noCursor.resources[0].endpoint).toBe(false)
    })

    it('omits cursor_type when it equals the backend default (datetime)', () => {
        const state = baseState()
        state.tables[0].incremental_enabled = true
        state.tables[0].cursor_path = 'updated_at'
        const manifest = buildManifest(state) as any
        expect('cursor_type' in manifest.resources[0].endpoint.incremental).toBe(false)
    })

    it.each(['date', 'timestamp', 'integer'] as const)('emits cursor_type=%s when non-default', (cursorType) => {
        const state = baseState()
        state.tables[0].incremental_enabled = true
        state.tables[0].cursor_path = 'updated_at'
        state.tables[0].cursor_type = cursorType
        const manifest = buildManifest(state) as any
        expect(manifest.resources[0].endpoint.incremental.cursor_type).toBe(cursorType)
    })

    it('emits sort_mode only when explicitly descending', () => {
        const asc = buildManifest(baseState()) as any
        expect('sort_mode' in asc.resources[0]).toBe(false)

        const descState = baseState()
        descState.tables[0].sort_mode = 'desc'
        const desc = buildManifest(descState) as any
        expect(desc.resources[0].sort_mode).toBe('desc')
    })
})

describe('parseManifestIntoState', () => {
    it('returns defaults for undefined/empty input', () => {
        const state = parseManifestIntoState(undefined)
        expect(state.base_url).toBe('')
        expect(state.auth_type).toBe('bearer')
        expect(state.tables).toHaveLength(1)
    })

    it('returns defaults for invalid JSON', () => {
        const state = parseManifestIntoState('{not json}')
        expect(state.tables).toHaveLength(1)
    })

    it('round-trips a manifest through build → parse → build without drift', () => {
        const original = baseState()
        original.headers = [{ id: 'h1', key: 'X-Workspace', value: 'acme' }]
        original.tables = [
            {
                id: 'table-orders',
                name: 'orders',
                path: '/orders',
                method: 'POST',
                data_selector: 'records',
                primary_key: 'order_id, line_no',
                paginator: { type: 'cursor', cursor_path: 'meta.next', cursor_param: 'after' },
                sort_mode: 'asc',
                incremental_enabled: true,
                cursor_path: 'updated_at',
                cursor_type: 'datetime',
                start_param: 'since',
                datetime_format: '',
                parent_table: '',
                parent_resolve_field: '',
                parent_path_param: '',
                include_from_parent: '',
                passthrough_params: {},
            },
        ]

        const firstJson = JSON.stringify(buildManifest(original))
        const reparsed = parseManifestIntoState(firstJson)
        const secondJson = JSON.stringify(buildManifest(reparsed))
        expect(secondJson).toBe(firstJson)
    })

    it.each([
        ['offset', { type: 'offset', limit: 50, offset_param: 'o', limit_param: 'l' }],
        ['page_number (base_page 0)', { type: 'page_number', page_param: 'p', base_page: 0 }],
        ['json_response', { type: 'json_response', next_url_path: 'paging.next' }],
        ['header_link', { type: 'header_link', links_next_key: 'successor' }],
    ] as const)('round-trips the %s paginator without drift', (_name, paginator) => {
        const original = baseState()
        original.tables[0].paginator = { ...paginator }
        const firstJson = JSON.stringify(buildManifest(original))
        const secondJson = JSON.stringify(buildManifest(parseManifestIntoState(firstJson)))
        expect(secondJson).toBe(firstJson)
    })

    it('flattens a single-element primary_key array back to a string-ish form on parse', () => {
        const manifestJson = JSON.stringify({
            client: { base_url: 'https://x' },
            resources: [{ name: 'r', primary_key: ['id'], endpoint: { path: '/r' } }],
        })
        const state = parseManifestIntoState(manifestJson)
        expect(state.tables[0].primary_key).toBe('id')
    })

    it('falls back to single_page paginator when type is unknown', () => {
        const manifestJson = JSON.stringify({
            client: { base_url: 'https://x' },
            resources: [{ name: 'r', endpoint: { path: '/r', paginator: { type: 'wat' } } }],
        })
        const state = parseManifestIntoState(manifestJson)
        expect(state.tables[0].paginator.type).toBe('single_page')
    })

    it("recognizes 'none' auth when type isn't one of the supported set", () => {
        const manifestJson = JSON.stringify({
            client: { base_url: 'https://x', auth: { type: 'oauth' } },
            resources: [{ name: 'r', endpoint: { path: '/r' } }],
        })
        const state = parseManifestIntoState(manifestJson)
        expect(state.auth_type).toBe('none')
    })

    it.each(['query', 'cookie'] as const)('parses api_key location=%s out of the manifest', (location) => {
        const manifestJson = JSON.stringify({
            client: { base_url: 'https://x', auth: { type: 'api_key', name: 'k', location } },
            resources: [{ name: 'r', endpoint: { path: '/r' } }],
        })
        const state = parseManifestIntoState(manifestJson)
        expect(state.auth_api_key_location).toBe(location)
    })

    it("folds the dead 'param' alias to 'query' on parse", () => {
        // Backend treats both as the same (auth.py:41), so the UI never has to
        // distinguish them. A manifest authored elsewhere should still parse.
        const manifestJson = JSON.stringify({
            client: { base_url: 'https://x', auth: { type: 'api_key', name: 'k', location: 'param' } },
            resources: [{ name: 'r', endpoint: { path: '/r' } }],
        })
        const state = parseManifestIntoState(manifestJson)
        expect(state.auth_api_key_location).toBe('query')
    })

    it("folds a legacy 'auto' paginator to single_page on parse", () => {
        // 'auto' was a no-op alias for single_page (it mapped to no paginator on
        // the backend) and is no longer offered. Manifests authored before it was
        // removed should still parse without surfacing the dead type.
        const manifestJson = JSON.stringify({
            client: { base_url: 'https://x' },
            resources: [{ name: 'r', endpoint: { path: '/r', paginator: { type: 'auto' } } }],
        })
        const state = parseManifestIntoState(manifestJson)
        expect(state.tables[0].paginator.type).toBe('single_page')
    })

    it.each(['date', 'timestamp', 'integer'] as const)(
        'parses cursor_type=%s from incremental config',
        (cursorType) => {
            const manifestJson = JSON.stringify({
                client: { base_url: 'https://x' },
                resources: [
                    {
                        name: 'r',
                        endpoint: { path: '/r', incremental: { cursor_path: 'c', cursor_type: cursorType } },
                    },
                ],
            })
            const state = parseManifestIntoState(manifestJson)
            expect(state.tables[0].cursor_type).toBe(cursorType)
        }
    )

    it('falls back to datetime cursor_type for an unknown value', () => {
        const manifestJson = JSON.stringify({
            client: { base_url: 'https://x' },
            resources: [
                {
                    name: 'r',
                    endpoint: { path: '/r', incremental: { cursor_path: 'c', cursor_type: 'bogus' } },
                },
            ],
        })
        const state = parseManifestIntoState(manifestJson)
        expect(state.tables[0].cursor_type).toBe('datetime')
    })

    it.each(['asc', 'desc'] as const)('parses sort_mode=%s from the resource', (mode) => {
        const manifestJson = JSON.stringify({
            client: { base_url: 'https://x' },
            resources: [{ name: 'r', endpoint: { path: '/r' }, sort_mode: mode }],
        })
        const state = parseManifestIntoState(manifestJson)
        expect(state.tables[0].sort_mode).toBe(mode)
    })

    it('round-trips all new fields without drift', () => {
        const original = baseState()
        original.auth_type = 'api_key'
        original.auth_api_key_name = 'X-Key'
        original.auth_api_key_location = 'query'
        original.tables = [
            {
                id: 'table-events',
                name: 'events',
                path: '/events',
                method: 'GET',
                data_selector: 'data',
                primary_key: 'id',
                paginator: { type: 'single_page' },
                sort_mode: 'desc',
                incremental_enabled: true,
                cursor_path: 'updated_at',
                cursor_type: 'timestamp',
                start_param: 'since',
                datetime_format: '',
                parent_table: '',
                parent_resolve_field: '',
                parent_path_param: '',
                include_from_parent: '',
                passthrough_params: {},
            },
        ]

        const firstJson = JSON.stringify(buildManifest(original))
        const secondJson = JSON.stringify(buildManifest(parseManifestIntoState(firstJson)))
        expect(secondJson).toBe(firstJson)
    })
})

// Spreads the base table so new TableForm fields only need a default in
// baseState(), not in every fixture.
const makeTable = (overrides: Partial<TableForm>): TableForm => ({
    ...baseState().tables[0],
    ...overrides,
})

describe('fan-out (parent/child)', () => {
    const childState = (): ManifestState => {
        const state = baseState()
        state.tables = [
            makeTable({
                id: 'table-forms',
                name: 'forms',
                path: '/forms',
                data_selector: 'items',
            }),
            makeTable({
                id: 'table-responses',
                name: 'responses',
                path: '/forms/{form_id}/responses',
                data_selector: 'items',
                primary_key: 'token',
                parent_table: 'forms',
                parent_resolve_field: 'id',
                parent_path_param: 'form_id',
                include_from_parent: 'id, title',
            }),
        ]
        return state
    }

    it('emits a resolve param binding the parent field into the path placeholder', () => {
        const manifest = buildManifest(childState()) as any
        expect(manifest.resources[1].endpoint.params).toEqual({
            form_id: { type: 'resolve', resource: 'forms', field: 'id' },
        })
    })

    it('emits include_from_parent as a list when fields are provided', () => {
        const manifest = buildManifest(childState()) as any
        expect(manifest.resources[1].include_from_parent).toEqual(['id', 'title'])
    })

    it('still emits the resolve param when the dependency is half-filled, so the backend rejects it loudly', () => {
        // Silently dropping a half-filled dependency would sync the table as an
        // unrelated top-level endpoint — wrong data with no error anywhere.
        const state = childState()
        state.tables[1].parent_path_param = '' // missing placeholder name
        const manifest = buildManifest(state) as any
        expect(manifest.resources[1].endpoint.params).toEqual({
            '': { type: 'resolve', resource: 'forms', field: 'id' },
        })
    })

    it('omits include_from_parent when no parent fields are listed', () => {
        const state = childState()
        state.tables[1].include_from_parent = ''
        const manifest = buildManifest(state) as any
        expect('params' in manifest.resources[1].endpoint).toBe(true)
        expect('include_from_parent' in manifest.resources[1]).toBe(false)
    })

    it('keeps the top-level parent table free of a resolve param', () => {
        const manifest = buildManifest(childState()) as any
        expect('params' in manifest.resources[0].endpoint).toBe(false)
    })

    it('offers only top-level tables as parents — one level of nesting, no cycles', () => {
        const state = childState()
        state.tables.push({
            ...state.tables[0],
            id: 'table-users',
            name: 'users',
            path: '/users',
        })
        // The child table may pick either top-level table, but not itself.
        expect(eligibleParentTables(state.tables, 1)).toEqual(['forms', 'users'])
        // A top-level table can't pick the child (it has a parent) — so mutual
        // cycles and grandchildren are unbuildable.
        expect(eligibleParentTables(state.tables, 0)).toEqual(['users'])
        expect(eligibleParentTables(state.tables, 2)).toEqual(['forms'])
    })

    it('renaming a parent table follows through to its children', () => {
        const tables = updateTableInList(childState().tables, 0, { name: 'surveys' })
        expect(tables[0].name).toBe('surveys')
        expect(tables[1].parent_table).toBe('surveys')
    })

    it('removing a parent table clears its children back to top-level', () => {
        const tables = removeTableFromList(childState().tables, 0)
        expect(tables).toHaveLength(1)
        expect(tables[0].parent_table).toBe('')
        expect(tables[0].parent_resolve_field).toBe('')
        expect(tables[0].parent_path_param).toBe('')
        expect(tables[0].include_from_parent).toBe('')
    })

    it('keeps children attached when a duplicate-named table is removed', () => {
        // A sibling still carries the removed name, so the child's parent
        // reference remains satisfiable and must not be cleared.
        const state = childState()
        state.tables.push(makeTable({ id: 'table-forms-2', name: 'forms', path: '/forms-v2' }))
        const tables = removeTableFromList(state.tables, 0)
        expect(tables.find((table) => table.name === 'responses')?.parent_table).toBe('forms')
    })

    it('rename to a colliding name still cascades — the backend rejects the duplicate at save', () => {
        const state = childState()
        state.tables.push(makeTable({ id: 'table-surveys', name: 'surveys', path: '/surveys' }))
        const tables = updateTableInList(state.tables, 0, { name: 'surveys' })
        expect(tables[1].parent_table).toBe('surveys')
    })

    it('keeps the first resolve param as the dependency when a manifest carries two', () => {
        // The backend rejects multi-resolve manifests, but the parse path can
        // still be handed one (raw JSON authoring) — the first becomes the
        // editable dependency, the rest ride along in passthrough_params so a
        // builder edit re-emits (and the backend re-rejects) them honestly.
        const manifest = buildManifest(childState()) as any
        manifest.resources[1].endpoint.params.other_id = { type: 'resolve', resource: 'forms', field: 'id' }
        const child = parseManifestIntoState(JSON.stringify(manifest)).tables[1]
        expect(child.parent_path_param).toBe('form_id')
        expect(child.passthrough_params).toEqual({ other_id: { type: 'resolve', resource: 'forms', field: 'id' } })
    })

    it('preserves raw-authored static params through a builder round-trip', () => {
        // The builder has no UI for static query params, but editing a table
        // must not silently drop ones authored in raw JSON.
        const manifest = buildManifest(childState()) as any
        manifest.resources[1].endpoint.params.status = 'active'
        const rebuilt = buildManifest(parseManifestIntoState(JSON.stringify(manifest))) as any
        expect(rebuilt.resources[1].endpoint.params).toEqual({
            status: 'active',
            form_id: { type: 'resolve', resource: 'forms', field: 'id' },
        })
    })

    it('preserves a top-level table’s static params even with no parent dependency', () => {
        const manifest = buildManifest(childState()) as any
        manifest.resources[0].endpoint.params = { limit: 100 }
        const rebuilt = buildManifest(parseManifestIntoState(JSON.stringify(manifest))) as any
        expect(rebuilt.resources[0].endpoint.params).toEqual({ limit: 100 })
    })

    it('hydrates the parent dependency back out on parse', () => {
        const state = parseManifestIntoState(JSON.stringify(buildManifest(childState())))
        const child = state.tables[1]
        expect(child.parent_table).toBe('forms')
        expect(child.parent_resolve_field).toBe('id')
        expect(child.parent_path_param).toBe('form_id')
        expect(child.include_from_parent).toBe('id, title')
    })

    it('round-trips a fan-out manifest through build → parse → build without drift', () => {
        const firstJson = JSON.stringify(buildManifest(childState()))
        const secondJson = JSON.stringify(buildManifest(parseManifestIntoState(firstJson)))
        expect(secondJson).toBe(firstJson)
    })
})

describe('datetime_format (incremental cursor)', () => {
    const incrementalState = (datetimeFormat: string): ManifestState => {
        const state = baseState()
        state.tables[0].incremental_enabled = true
        state.tables[0].cursor_path = 'updated_at'
        state.tables[0].datetime_format = datetimeFormat
        return state
    }

    it('emits datetime_format inside endpoint.incremental when set', () => {
        const manifest = buildManifest(incrementalState('%Y-%m-%dT%H:%M:%SZ')) as any
        expect(manifest.resources[0].endpoint.incremental.datetime_format).toBe('%Y-%m-%dT%H:%M:%SZ')
    })

    it('omits datetime_format when blank', () => {
        const manifest = buildManifest(incrementalState('   ')) as any
        expect('datetime_format' in manifest.resources[0].endpoint.incremental).toBe(false)
    })

    it('hydrates datetime_format on parse and round-trips without drift', () => {
        const firstJson = JSON.stringify(buildManifest(incrementalState('%Y-%m-%dT%H:%M:%SZ')))
        expect(parseManifestIntoState(firstJson).tables[0].datetime_format).toBe('%Y-%m-%dT%H:%M:%SZ')
        expect(JSON.stringify(buildManifest(parseManifestIntoState(firstJson)))).toBe(firstJson)
    })
})

describe('extractAuthSecrets', () => {
    const noSecrets = {
        auth_token: '',
        auth_api_key: '',
        auth_password: '',
        auth_oauth2_client_secret: '',
        auth_oauth2_refresh_token: '',
    }

    it('returns only the bearer token for bearer auth', () => {
        const state = baseState()
        state.auth_type = 'bearer'
        state.auth_token = 'tok_123'
        expect(extractAuthSecrets(state)).toEqual({ ...noSecrets, auth_token: 'tok_123' })
    })

    it('returns only the api key for api_key auth', () => {
        const state = baseState()
        state.auth_type = 'api_key'
        state.auth_api_key = 'sk_test'
        expect(extractAuthSecrets(state)).toEqual({ ...noSecrets, auth_api_key: 'sk_test' })
    })

    it('returns only the password for http_basic auth', () => {
        const state = baseState()
        state.auth_type = 'http_basic'
        state.auth_password = 'hunter2'
        expect(extractAuthSecrets(state)).toEqual({ ...noSecrets, auth_password: 'hunter2' })
    })

    it('returns all-empty for none auth, ignoring stale credential state', () => {
        const state = baseState()
        state.auth_type = 'none'
        // All stale so each ternary's false-arm is genuinely exercised.
        state.auth_token = 'tok_123'
        state.auth_api_key = 'sk_test'
        state.auth_password = 'hunter2'
        state.oauth2_client_secret = 'cs_123'
        state.oauth2_refresh_token = 'rt_123'
        expect(extractAuthSecrets(state)).toEqual(noSecrets)
    })

    it('returns the client secret for the client_credentials grant, but never a refresh token', () => {
        const state = baseState()
        state.auth_type = 'oauth2'
        state.oauth2_grant_type = 'client_credentials'
        state.oauth2_client_secret = 'cs_123'
        // A stale refresh token must not leak: client_credentials has no refresh token.
        state.oauth2_refresh_token = 'rt_stale'
        expect(extractAuthSecrets(state)).toEqual({ ...noSecrets, auth_oauth2_client_secret: 'cs_123' })
    })

    it('returns both secrets for the refresh_token grant', () => {
        const state = baseState()
        state.auth_type = 'oauth2'
        state.oauth2_grant_type = 'refresh_token'
        state.oauth2_client_secret = 'cs_123'
        state.oauth2_refresh_token = 'rt_123'
        expect(extractAuthSecrets(state)).toEqual({
            ...noSecrets,
            auth_oauth2_client_secret: 'cs_123',
            auth_oauth2_refresh_token: 'rt_123',
        })
    })
})

describe('visibleAuthTypes', () => {
    it.each([
        [false, 'bearer', false], // flag off, not oauth2 -> hidden
        [false, 'oauth2', true], // flag off, already oauth2 -> kept visible so the select can't rewrite it
        [true, 'bearer', true], // flag on -> visible
        [true, 'oauth2', true], // flag on, already oauth2 -> visible
    ] as const)('oauth2 visible? (enabled=%s, current=%s)', (enabled, current, visible) => {
        expect(visibleAuthTypes(enabled, current).includes('oauth2')).toBe(visible)
    })

    it('never drops the non-oauth2 types', () => {
        expect(visibleAuthTypes(false, 'bearer')).toEqual(['none', 'bearer', 'api_key', 'http_basic'])
    })
})

describe('oauth2 manifest round-trip', () => {
    const oauth2Manifest = JSON.stringify({
        client: {
            base_url: 'https://api.example.com',
            auth: {
                type: 'oauth2',
                client_id: 'client-abc',
                token_url: 'https://auth.example.com/oauth2/token',
                grant_type: 'client_credentials',
                scopes: 'read:users read:orders',
                client_auth_method: 'basic',
                access_token_name: 'token',
                expires_in_name: 'expires_at',
                expiry_date_format: '%Y-%m-%dT%H:%M:%SZ',
                extra_token_request_params: { audience: 'https://api.example.com' },
                token_request_headers: { 'X-Tenant': 'acme' },
            },
        },
        resources: [
            {
                name: 'users',
                primary_key: 'id',
                endpoint: { path: '/users', data_selector: 'data', paginator: { type: 'single_page' } },
            },
        ],
    })

    it('parses non-secret oauth fields and leaves secrets empty', () => {
        const state = parseManifestIntoState(oauth2Manifest)
        expect(state.auth_type).toBe('oauth2')
        expect(state.oauth2_client_id).toBe('client-abc')
        expect(state.oauth2_token_url).toBe('https://auth.example.com/oauth2/token')
        expect(state.oauth2_grant_type).toBe('client_credentials')
        expect(state.oauth2_scopes).toBe('read:users read:orders')
        expect(state.oauth2_client_auth_method).toBe('basic')
        // Secrets are never in the manifest, so they parse back empty.
        expect(state.oauth2_client_secret).toBe('')
        expect(state.oauth2_refresh_token).toBe('')
    })

    it('round-trips the auth manifest without secrets or scope corruption', () => {
        const rebuilt = buildManifest(parseManifestIntoState(oauth2Manifest)) as any
        const auth = rebuilt.client.auth
        expect(auth.type).toBe('oauth2')
        expect(auth.client_id).toBe('client-abc')
        expect(auth.token_url).toBe('https://auth.example.com/oauth2/token')
        expect(auth.grant_type).toBe('client_credentials')
        // Scopes stay a single space-separated string end-to-end — never split/rejoined.
        expect(auth.scopes).toBe('read:users read:orders')
        expect(auth.client_auth_method).toBe('basic')
        expect(auth.access_token_name).toBe('token')
        expect(auth.expires_in_name).toBe('expires_at')
        expect(auth.expiry_date_format).toBe('%Y-%m-%dT%H:%M:%SZ')
        // Advanced dict knobs with no builder UI survive verbatim (like passthrough_params).
        expect(auth.extra_token_request_params).toEqual({ audience: 'https://api.example.com' })
        expect(auth.token_request_headers).toEqual({ 'X-Tenant': 'acme' })
        // Secrets never appear in the manifest.
        expect(auth.client_secret).toBeUndefined()
        expect(auth.refresh_token).toBeUndefined()
    })

    it('drops an inline client_secret rather than re-emitting it', () => {
        // Even if a hand-authored manifest inlines the secret, parse drops it and build never
        // re-emits it — the secret only ever travels via extractAuthSecrets / the secret field.
        const withInlineSecret = JSON.parse(oauth2Manifest)
        withInlineSecret.client.auth.client_secret = 'should-not-survive'
        const rebuilt = buildManifest(parseManifestIntoState(JSON.stringify(withInlineSecret))) as any
        expect(rebuilt.client.auth.client_secret).toBeUndefined()
    })

    it('omits client_auth_method when it is the default (body)', () => {
        const bodyManifest = JSON.parse(oauth2Manifest)
        bodyManifest.client.auth.client_auth_method = 'body'
        const rebuilt = buildManifest(parseManifestIntoState(JSON.stringify(bodyManifest))) as any
        expect(rebuilt.client.auth.client_auth_method).toBeUndefined()
    })

    it('coerces token-param values to strings and drops non-scalars to match the backend dict[str, str]', () => {
        // A hand/AI-authored manifest with non-string values would otherwise round-trip verbatim and
        // fail backend validation; normalize scalars to strings and drop nested objects in the builder.
        const manifest = JSON.parse(oauth2Manifest)
        manifest.client.auth.extra_token_request_params = { audience: 'x', retries: 3, nested: { a: 1 } }
        const rebuilt = buildManifest(parseManifestIntoState(JSON.stringify(manifest))) as any
        expect(rebuilt.client.auth.extra_token_request_params).toEqual({ audience: 'x', retries: '3' })
    })
})
