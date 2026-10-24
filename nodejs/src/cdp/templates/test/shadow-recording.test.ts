import { NormalizeContext, normalizeRequests, normalizeValue } from './shadow-recording'

const CORPUS_UUID = '01920000-0000-7000-8000-000000000001'
const GENERATED_UUID = '7b3e2c1a-9f4d-4e8b-a1c2-3d4e5f6a7b8c'
const API_KEY = 'fake-secret-apiKey-0000'
const API_SECRET = 'fake-secret-apiSecret-0000'
const TEAM_ID = 4242

const context = (overrides: Partial<NormalizeContext> = {}): NormalizeContext => ({
    secrets: { apiKey: API_KEY, apiSecret: API_SECRET },
    inputText: '',
    teamId: TEAM_ID,
    ...overrides,
})

const base64 = (text: string): string => Buffer.from(text).toString('base64')
const jwt = (claims: object): string =>
    [{ alg: 'HS256' }, claims].map((part) => Buffer.from(JSON.stringify(part)).toString('base64url')).join('.') +
    '.fake-signature'

describe('normalizeRequests', () => {
    it('replaces each secret with its own marker, so swapping two secrets shows up', () => {
        const [request] = normalizeRequests(
            [
                {
                    method: 'POST',
                    url: `https://api.example.com/v1?key=${API_KEY}`,
                    headers: { Authorization: `Basic ${base64(`${API_KEY}:${API_SECRET}`)}` },
                    body: JSON.stringify({ token: API_SECRET }),
                },
            ],
            context()
        )

        expect(request).toEqual({
            method: 'POST',
            url: 'https://api.example.com/v1?key=<secret:apiKey>',
            headers: { Authorization: 'Basic <decoded><secret:apiKey>:<secret:apiSecret>' },
            body: { token: '<secret:apiSecret>' },
        })
    })

    it('masks secrets that a template URL-encodes, base64-encodes or embeds in an encoded value', () => {
        const [request] = normalizeRequests(
            [
                {
                    method: 'POST',
                    url: `https://api.example.com/v1?key=${encodeURIComponent(`${API_KEY} x`)}`,
                    headers: {},
                    body: JSON.stringify({ plain: base64(API_KEY), embedded: base64(`user:${API_SECRET}`) }),
                },
            ],
            context()
        )

        expect(JSON.stringify(request)).not.toMatch(/fake-secret|ZmFrZS1zZWNyZX/)
        expect(request.body).toEqual({
            embedded: '<base64>user:<secret:apiSecret></base64>',
            plain: '<base64><secret:apiKey></base64>',
        })
    })

    it('numbers generated UUIDs in order of appearance and keeps UUIDs from the input', () => {
        const requests = normalizeRequests(
            [
                {
                    method: 'POST',
                    url: `https://api.example.com/events/${CORPUS_UUID}`,
                    headers: { 'Idempotency-Key': GENERATED_UUID },
                    body: JSON.stringify({ dedupe_id: GENERATED_UUID, event_id: CORPUS_UUID }),
                },
            ],
            context({ inputText: JSON.stringify({ uuid: CORPUS_UUID }) })
        )

        expect(requests).toEqual([
            {
                method: 'POST',
                url: `https://api.example.com/events/${CORPUS_UUID}`,
                headers: { 'Idempotency-Key': '<uuid-1>' },
                body: { dedupe_id: '<uuid-1>', event_id: CORPUS_UUID },
            },
        ])
    })

    it('sorts header and body keys so the same request always serializes the same way', () => {
        const [first] = normalizeRequests(
            [
                {
                    method: 'post',
                    url: 'https://example.com',
                    headers: { b: '1', a: '2' },
                    body: '{"z":1,"y":{"d":1,"c":2}}',
                },
            ],
            context()
        )

        expect(JSON.stringify(first)).toEqual(
            '{"method":"POST","url":"https://example.com","headers":{"a":"2","b":"1"},"body":{"y":{"c":2,"d":1},"z":1}}'
        )
    })

    it('replaces the team id, which changes on every run, in paths and project links', () => {
        const [request] = normalizeRequests(
            [{ method: 'GET', url: `http://localhost:8000/api/projects/${TEAM_ID}/tickets/42420`, headers: {} }],
            context()
        )

        expect(request.url).toEqual('http://localhost:8000/api/projects/<team_id>/tickets/42420')
        expect(
            normalizeValue({ link: `https://us.posthog.com/project/${TEAM_ID}/events/1`, count: TEAM_ID }, context())
        ).toEqual({
            link: 'https://us.posthog.com/project/<team_id>/events/1',
            count: TEAM_ID,
        })
    })

    it('replaces a signed token with its claims, so only a change in what it grants shows up', () => {
        const token = jwt({ team_id: TEAM_ID, scope: 'tickets', sub: { name: 'Ada' } })

        const [request] = normalizeRequests(
            [
                {
                    method: 'POST',
                    url: 'https://example.com',
                    headers: { Authorization: `Bearer ${token}` },
                    body: JSON.stringify({ token }),
                },
            ],
            context()
        )

        const rendered = '<jwt scope=tickets sub={"name":"Ada"} team_id=<team_id>>'
        expect(request.headers.Authorization).toEqual(`Bearer ${rendered}`)
        expect(request.body).toEqual({ token: rendered })
        expect(normalizeValue({ token }, context())).toEqual({ token: rendered })
    })

    it('replaces a request signature, which covers the generated delivery id, with a marker', () => {
        const [request] = normalizeRequests(
            [
                {
                    method: 'POST',
                    url: 'https://example.com/hook',
                    headers: {
                        'webhook-signature': 'v1,lyu7pn9mmJGM2puXu8BxZueoL8L4A3MFgwwEg11wPmE=',
                        'X-Hub-Signature-256': 'sha256=ab12',
                    },
                },
            ],
            context()
        )

        expect(request.headers).toEqual({ 'X-Hub-Signature-256': '<signature>', 'webhook-signature': '<signature>' })
    })

    it('leaves a token-like value whose claims do not parse as it is', () => {
        const notAToken = 'eyJub3QganNvbg.eyJub3QganNvbg.signature'

        expect(normalizeValue({ value: notAToken }, context())).toEqual({ value: notAToken })
    })
})
