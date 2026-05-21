import { buildManifest, extractAuthSecrets, ManifestState, parseManifestIntoState } from './CustomSourceManifestBuilder'

const baseState = (): ManifestState => ({
    base_url: 'https://api.example.com',
    auth_type: 'bearer',
    auth_token: 'tok_123',
    auth_api_key: '',
    auth_api_key_name: 'Authorization',
    auth_username: '',
    auth_password: '',
    headers: [],
    streams: [
        {
            name: 'users',
            path: '/v1/users',
            method: 'GET',
            data_selector: 'data',
            primary_key: 'id',
            paginator: { type: 'single_page' },
            incremental_enabled: false,
            cursor_path: '',
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
            { key: 'X-Workspace', value: 'acme' },
            { key: '', value: 'ignored' },
            { key: '  ', value: 'also ignored' },
        ]
        const manifest = buildManifest(state) as any
        expect(manifest.client.headers).toEqual({ 'X-Workspace': 'acme' })
    })

    it('omits client.headers entirely when no real entries are present', () => {
        const state = baseState()
        state.headers = [{ key: '', value: 'whatever' }]
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
        pageState.streams[0].paginator = { type: 'page_number', page_param: 'p', initial_page: 0 }
        const pageManifest = buildManifest(pageState) as any
        expect(pageManifest.resources[0].endpoint.paginator).toEqual({
            type: 'page_number',
            page_param: 'p',
            initial_page: 0,
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
        original.headers = [{ key: 'X-Workspace', value: 'acme' }]
        original.streams = [
            {
                name: 'orders',
                path: '/orders',
                method: 'POST',
                data_selector: 'records',
                primary_key: 'order_id, line_no',
                paginator: { type: 'cursor', cursor_path: 'meta.next', cursor_param: 'after' },
                incremental_enabled: true,
                cursor_path: 'updated_at',
                start_param: 'since',
            },
        ]

        const firstJson = JSON.stringify(buildManifest(original))
        const reparsed = parseManifestIntoState(firstJson)
        const secondJson = JSON.stringify(buildManifest(reparsed))
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
})

describe('extractAuthSecrets', () => {
    it('returns only the bearer token for bearer auth', () => {
        const state = baseState()
        state.auth_type = 'bearer'
        state.auth_token = 'tok_123'
        expect(extractAuthSecrets(state)).toEqual({ auth_token: 'tok_123', auth_api_key: '', auth_password: '' })
    })

    it('returns only the api key for api_key auth', () => {
        const state = baseState()
        state.auth_type = 'api_key'
        state.auth_api_key = 'sk_test'
        expect(extractAuthSecrets(state)).toEqual({ auth_token: '', auth_api_key: 'sk_test', auth_password: '' })
    })

    it('returns only the password for http_basic auth', () => {
        const state = baseState()
        state.auth_type = 'http_basic'
        state.auth_password = 'hunter2'
        expect(extractAuthSecrets(state)).toEqual({ auth_token: '', auth_api_key: '', auth_password: 'hunter2' })
    })

    it('returns all-empty for none auth, ignoring stale credential state', () => {
        const state = baseState()
        state.auth_type = 'none'
        state.auth_token = 'tok_123'
        expect(extractAuthSecrets(state)).toEqual({ auth_token: '', auth_api_key: '', auth_password: '' })
    })
})
