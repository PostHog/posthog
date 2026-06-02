import { buildManifest, extractAuthSecrets, ManifestState, parseManifestIntoState } from '../customSourceManifest'

const baseState = (): ManifestState => ({
    base_url: 'https://api.example.com',
    auth_type: 'bearer',
    auth_token: 'tok_123',
    auth_api_key: '',
    auth_api_key_name: 'Authorization',
    auth_api_key_location: 'header',
    auth_username: '',
    auth_password: '',
    auth_oauth_token_url: '',
    auth_oauth_client_id: '',
    auth_oauth_grant_type: 'client_credentials',
    auth_oauth_scopes: '',
    auth_oauth_client_secret: '',
    auth_oauth_refresh_token: '',
    headers: [],
    streams: [
        {
            id: 'stream-base',
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
        state.streams[0].primary_key = 'user_id, page_url, day'
        const manifest = buildManifest(state) as any
        expect(manifest.resources[0].primary_key).toEqual(['user_id', 'page_url', 'day'])
    })

    it('keeps a single primary_key as a string', () => {
        const manifest = buildManifest(baseState()) as any
        expect(manifest.resources[0].primary_key).toEqual('id')
    })

    it.each(['', '   ', ' , '])('falls back to id when primary_key is cleared (%p)', (cleared) => {
        const state = baseState()
        state.streams[0].primary_key = cleared
        const manifest = buildManifest(state) as any
        expect(manifest.resources[0].primary_key).toEqual('id')
    })

    it("only sets endpoint.method when the stream isn't GET", () => {
        const get = buildManifest(baseState()) as any
        expect('method' in get.resources[0].endpoint).toBe(false)

        const state = baseState()
        state.streams[0].method = 'POST'
        const post = buildManifest(state) as any
        expect(post.resources[0].endpoint.method).toBe('POST')
    })

    it('serializes paginator-specific fields per paginator type', () => {
        const offsetState = baseState()
        offsetState.streams[0].paginator = { type: 'offset', limit: 50, offset_param: 'o', limit_param: 'l' }
        const offsetManifest = buildManifest(offsetState) as any
        expect(offsetManifest.resources[0].endpoint.paginator).toEqual({
            type: 'offset',
            limit: 50,
            offset_param: 'o',
            limit_param: 'l',
        })

        const pageState = baseState()
        pageState.streams[0].paginator = { type: 'page_number', page_param: 'p', base_page: 0 }
        const pageManifest = buildManifest(pageState) as any
        expect(pageManifest.resources[0].endpoint.paginator).toEqual({
            type: 'page_number',
            page_param: 'p',
            base_page: 0,
        })
    })

    it('fills paginator defaults when fields are left blank', () => {
        const state = baseState()
        state.streams[0].paginator = { type: 'cursor' }
        const manifest = buildManifest(state) as any
        expect(manifest.resources[0].endpoint.paginator).toEqual({
            type: 'cursor',
            cursor_path: 'meta.next_cursor',
            cursor_param: 'cursor',
        })
    })

    it('serializes json_response with an explicit and a default next_url_path', () => {
        const explicit = baseState()
        explicit.streams[0].paginator = { type: 'json_response', next_url_path: 'paging.next' }
        expect((buildManifest(explicit) as any).resources[0].endpoint.paginator).toEqual({
            type: 'json_response',
            next_url_path: 'paging.next',
        })

        const blank = baseState()
        blank.streams[0].paginator = { type: 'json_response' }
        expect((buildManifest(blank) as any).resources[0].endpoint.paginator).toEqual({
            type: 'json_response',
            next_url_path: 'links.next',
        })
    })

    it('serializes header_link with an explicit and a default links_next_key', () => {
        const explicit = baseState()
        explicit.streams[0].paginator = { type: 'header_link', links_next_key: 'successor' }
        expect((buildManifest(explicit) as any).resources[0].endpoint.paginator).toEqual({
            type: 'header_link',
            links_next_key: 'successor',
        })

        const blank = baseState()
        blank.streams[0].paginator = { type: 'header_link' }
        expect((buildManifest(blank) as any).resources[0].endpoint.paginator).toEqual({
            type: 'header_link',
            links_next_key: 'next',
        })
    })

    it('emits endpoint.incremental only when enabled AND cursor_path is set', () => {
        const state = baseState()
        state.streams[0].incremental_enabled = true
        state.streams[0].cursor_path = 'updated_at'
        const manifest = buildManifest(state) as any
        expect(manifest.resources[0].endpoint.incremental).toEqual({
            cursor_path: 'updated_at',
            start_param: 'updated_at',
        })

        state.streams[0].start_param = 'since'
        const overriddenStart = buildManifest(state) as any
        expect(overriddenStart.resources[0].endpoint.incremental.start_param).toBe('since')

        state.streams[0].cursor_path = ''
        const noCursor = buildManifest(state) as any
        expect('incremental' in noCursor.resources[0].endpoint).toBe(false)
    })

    it('omits cursor_type when it equals the backend default (datetime)', () => {
        const state = baseState()
        state.streams[0].incremental_enabled = true
        state.streams[0].cursor_path = 'updated_at'
        const manifest = buildManifest(state) as any
        expect('cursor_type' in manifest.resources[0].endpoint.incremental).toBe(false)
    })

    it.each(['date', 'timestamp', 'integer'] as const)('emits cursor_type=%s when non-default', (cursorType) => {
        const state = baseState()
        state.streams[0].incremental_enabled = true
        state.streams[0].cursor_path = 'updated_at'
        state.streams[0].cursor_type = cursorType
        const manifest = buildManifest(state) as any
        expect(manifest.resources[0].endpoint.incremental.cursor_type).toBe(cursorType)
    })

    it('emits sort_mode only when explicitly descending', () => {
        const asc = buildManifest(baseState()) as any
        expect('sort_mode' in asc.resources[0]).toBe(false)

        const descState = baseState()
        descState.streams[0].sort_mode = 'desc'
        const desc = buildManifest(descState) as any
        expect(desc.resources[0].sort_mode).toBe('desc')
    })
})

describe('parseManifestIntoState', () => {
    it('returns defaults for undefined/empty input', () => {
        const state = parseManifestIntoState(undefined)
        expect(state.base_url).toBe('')
        expect(state.auth_type).toBe('bearer')
        expect(state.streams).toHaveLength(1)
    })

    it('returns defaults for invalid JSON', () => {
        const state = parseManifestIntoState('{not json}')
        expect(state.streams).toHaveLength(1)
    })

    it('round-trips a manifest through build → parse → build without drift', () => {
        const original = baseState()
        original.headers = [{ id: 'h1', key: 'X-Workspace', value: 'acme' }]
        original.streams = [
            {
                id: 'stream-orders',
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
        original.streams[0].paginator = { ...paginator }
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
        expect(state.streams[0].primary_key).toBe('id')
    })

    it('falls back to single_page paginator when type is unknown', () => {
        const manifestJson = JSON.stringify({
            client: { base_url: 'https://x' },
            resources: [{ name: 'r', endpoint: { path: '/r', paginator: { type: 'wat' } } }],
        })
        const state = parseManifestIntoState(manifestJson)
        expect(state.streams[0].paginator.type).toBe('single_page')
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
        expect(state.streams[0].paginator.type).toBe('single_page')
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
            expect(state.streams[0].cursor_type).toBe(cursorType)
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
        expect(state.streams[0].cursor_type).toBe('datetime')
    })

    it.each(['asc', 'desc'] as const)('parses sort_mode=%s from the resource', (mode) => {
        const manifestJson = JSON.stringify({
            client: { base_url: 'https://x' },
            resources: [{ name: 'r', endpoint: { path: '/r' }, sort_mode: mode }],
        })
        const state = parseManifestIntoState(manifestJson)
        expect(state.streams[0].sort_mode).toBe(mode)
    })

    it('round-trips all new fields without drift', () => {
        const original = baseState()
        original.auth_type = 'api_key'
        original.auth_api_key_name = 'X-Key'
        original.auth_api_key_location = 'query'
        original.streams = [
            {
                id: 'stream-events',
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
            },
        ]

        const firstJson = JSON.stringify(buildManifest(original))
        const secondJson = JSON.stringify(buildManifest(parseManifestIntoState(firstJson)))
        expect(secondJson).toBe(firstJson)
    })
})

describe('extractAuthSecrets', () => {
    it('returns only the bearer token for bearer auth', () => {
        const state = baseState()
        state.auth_type = 'bearer'
        state.auth_token = 'tok_123'
        expect(extractAuthSecrets(state)).toEqual({
            auth_token: 'tok_123',
            auth_api_key: '',
            auth_password: '',
            auth_client_secret: '',
            auth_refresh_token: '',
        })
    })

    it('returns only the api key for api_key auth', () => {
        const state = baseState()
        state.auth_type = 'api_key'
        state.auth_api_key = 'sk_test'
        expect(extractAuthSecrets(state)).toEqual({
            auth_token: '',
            auth_api_key: 'sk_test',
            auth_password: '',
            auth_client_secret: '',
            auth_refresh_token: '',
        })
    })

    it('returns only the password for http_basic auth', () => {
        const state = baseState()
        state.auth_type = 'http_basic'
        state.auth_password = 'hunter2'
        expect(extractAuthSecrets(state)).toEqual({
            auth_token: '',
            auth_api_key: '',
            auth_password: 'hunter2',
            auth_client_secret: '',
            auth_refresh_token: '',
        })
    })

    it('returns all-empty for none auth, ignoring stale credential state', () => {
        const state = baseState()
        state.auth_type = 'none'
        // All stale so each ternary's false-arm is genuinely exercised.
        state.auth_token = 'tok_123'
        state.auth_api_key = 'sk_test'
        state.auth_password = 'hunter2'
        state.auth_oauth_client_secret = 'cs'
        state.auth_oauth_refresh_token = 'rt'
        expect(extractAuthSecrets(state)).toEqual({
            auth_token: '',
            auth_api_key: '',
            auth_password: '',
            auth_client_secret: '',
            auth_refresh_token: '',
        })
    })

    it('returns the client secret for the oauth2 client_credentials grant (no refresh token)', () => {
        const state = baseState()
        state.auth_type = 'oauth2'
        state.auth_oauth_grant_type = 'client_credentials'
        state.auth_oauth_client_secret = 'cs_secret'
        state.auth_oauth_refresh_token = 'should_be_ignored'
        expect(extractAuthSecrets(state)).toEqual({
            auth_token: '',
            auth_api_key: '',
            auth_password: '',
            auth_client_secret: 'cs_secret',
            auth_refresh_token: '',
        })
    })

    it('returns client secret and refresh token for the oauth2 refresh_token grant', () => {
        const state = baseState()
        state.auth_type = 'oauth2'
        state.auth_oauth_grant_type = 'refresh_token'
        state.auth_oauth_client_secret = 'cs_secret'
        state.auth_oauth_refresh_token = 'rt_secret'
        expect(extractAuthSecrets(state)).toEqual({
            auth_token: '',
            auth_api_key: '',
            auth_password: '',
            auth_client_secret: 'cs_secret',
            auth_refresh_token: 'rt_secret',
        })
    })
})

describe('oauth2 manifest', () => {
    it('emits client.auth for oauth2 with non-secret fields only', () => {
        const state = baseState()
        state.auth_type = 'oauth2'
        state.auth_oauth_token_url = 'https://auth.example.com/token'
        state.auth_oauth_client_id = 'cid'
        state.auth_oauth_grant_type = 'client_credentials'
        state.auth_oauth_scopes = 'read write'
        state.auth_oauth_client_secret = 'must_not_inline'
        const manifest = buildManifest(state) as any
        expect(manifest.client.auth).toEqual({
            type: 'oauth2',
            token_url: 'https://auth.example.com/token',
            grant_type: 'client_credentials',
            client_id: 'cid',
            scopes: ['read', 'write'],
        })
        expect(manifest.client.auth.client_secret).toBeUndefined()
        expect(manifest.client.auth.refresh_token).toBeUndefined()
    })

    it('omits scopes and client_id when blank', () => {
        const state = baseState()
        state.auth_type = 'oauth2'
        state.auth_oauth_token_url = 'https://auth.example.com/token'
        state.auth_oauth_grant_type = 'refresh_token'
        const manifest = buildManifest(state) as any
        expect(manifest.client.auth).toEqual({
            type: 'oauth2',
            token_url: 'https://auth.example.com/token',
            grant_type: 'refresh_token',
        })
    })

    it('round-trips an oauth2 manifest through parse (secrets excluded)', () => {
        const state = baseState()
        state.auth_type = 'oauth2'
        state.auth_oauth_token_url = 'https://auth.example.com/token'
        state.auth_oauth_client_id = 'cid'
        state.auth_oauth_grant_type = 'refresh_token'
        state.auth_oauth_scopes = 'read write'
        const json = JSON.stringify(buildManifest(state))
        const parsed = parseManifestIntoState(json)
        expect(parsed.auth_type).toBe('oauth2')
        expect(parsed.auth_oauth_token_url).toBe('https://auth.example.com/token')
        expect(parsed.auth_oauth_client_id).toBe('cid')
        expect(parsed.auth_oauth_grant_type).toBe('refresh_token')
        expect(parsed.auth_oauth_scopes).toBe('read write')
    })

    it('parses scopes whether authored as an array or a string', () => {
        const asArray = parseManifestIntoState(
            JSON.stringify({
                client: { base_url: 'x', auth: { type: 'oauth2', token_url: 't', scopes: ['a', 'b'] } },
                resources: [{ name: 'r', endpoint: { path: '/r' } }],
            })
        )
        expect(asArray.auth_oauth_scopes).toBe('a b')
        const asString = parseManifestIntoState(
            JSON.stringify({
                client: { base_url: 'x', auth: { type: 'oauth2', token_url: 't', scopes: 'a b' } },
                resources: [{ name: 'r', endpoint: { path: '/r' } }],
            })
        )
        expect(asString.auth_oauth_scopes).toBe('a b')
    })
})
