import { normalizeRequests, normalizeValue } from './shadow-recording'

const CORPUS_UUID = '01920000-0000-7000-8000-000000000001'
const GENERATED_UUID = '7b3e2c1a-9f4d-4e8b-a1c2-3d4e5f6a7b8c'
const SECRET = 'fake-secret-apiKey-0000'

describe('normalizeRequests', () => {
    it('replaces sensitive values with a marker, also inside Basic auth', () => {
        const [request] = normalizeRequests(
            [
                {
                    method: 'POST',
                    url: `https://api.example.com/v1?key=${SECRET}`,
                    headers: {
                        Authorization: `Basic ${Buffer.from(`ACexample0000:${SECRET}`).toString('base64')}`,
                        'X-Api-Key': SECRET,
                    },
                    body: JSON.stringify({ token: SECRET }),
                },
            ],
            { sensitiveValues: [SECRET], inputText: '', teamId: 4242 }
        )

        expect(request).toEqual({
            method: 'POST',
            url: 'https://api.example.com/v1?key=<secret>',
            headers: { Authorization: 'Basic <decoded>ACexample0000:<secret>', 'X-Api-Key': '<secret>' },
            body: { token: '<secret>' },
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
            { sensitiveValues: [], inputText: JSON.stringify({ uuid: CORPUS_UUID }), teamId: 4242 }
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
            { sensitiveValues: [], inputText: '', teamId: 4242 }
        )

        expect(JSON.stringify(first)).toEqual(
            '{"method":"POST","url":"https://example.com","headers":{"a":"2","b":"1"},"body":{"y":{"c":2,"d":1},"z":1}}'
        )
    })

    it('replaces the team id, which changes on every run, in paths and project links', () => {
        const context = { sensitiveValues: [], inputText: '', teamId: 4242 }

        const [request] = normalizeRequests(
            [{ method: 'GET', url: 'http://localhost:8000/api/projects/4242/tickets/42420', headers: {} }],
            context
        )

        expect(request.url).toEqual('http://localhost:8000/api/projects/<team_id>/tickets/42420')
        expect(normalizeValue({ link: 'https://us.posthog.com/project/4242/events/1', count: 4242 }, context)).toEqual({
            link: 'https://us.posthog.com/project/<team_id>/events/1',
            count: 4242,
        })
    })

    it('replaces a signed token with its claims, so only a change in what it grants shows up', () => {
        const encode = (part: object): string => Buffer.from(JSON.stringify(part)).toString('base64url')
        const token = [encode({ alg: 'HS256' }), encode({ team_id: 4242, scope: 'tickets' }), 'fake-signature'].join(
            '.'
        )

        const [request] = normalizeRequests(
            [{ method: 'GET', url: 'https://example.com', headers: { Authorization: `Bearer ${token}` } }],
            { sensitiveValues: [], inputText: '', teamId: 4242 }
        )

        expect(request.headers.Authorization).toEqual('Bearer <jwt scope=tickets team_id=<team_id>>')
    })
})
