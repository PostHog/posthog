import { getResponse, HttpHandler, type HttpHandler as HttpHandlerType } from 'msw'

import { handlers } from '~/mocks/handlers'
import { routeHandlers } from '~/mocks/routeHandlers'

const markers: HttpHandlerType[] = handlers.map(
    (handler, index) => new HttpHandler(handler.info.method, handler.info.path, () => new Response(String(index)))
)

const answer = async (list: HttpHandlerType[], method: string, url: string): Promise<string> => {
    const response = await getResponse(list, new Request(new URL(url, 'http://localhost/'), { method }))
    return response ? await response.text() : 'unhandled'
}

const requestsFor = (handler: HttpHandlerType, index: number): [string, string][] => {
    const { method, path } = handler.info
    if (typeof path !== 'string' || typeof method !== 'string' || !path.startsWith('/')) {
        return []
    }
    const filled = path.replace(/:[^/]+/g, 'Abc1')
    const variants: [string, string][] = [
        [method, filled],
        [method, `${filled.toUpperCase()}?q=1`],
        [method, `${filled}/extra/`],
        [method === 'GET' ? 'POST' : 'GET', `${filled}/`],
    ]
    return [[method, `${filled}/`], variants[index % variants.length]]
}

describe('routeHandlers', () => {
    it('answers every request with the same default handler as msw', async () => {
        const router = [routeHandlers(markers)]
        const requests: [string, string][] = [
            ...markers.flatMap(requestsFor),
            ['GET', '/'],
            ['GET', '/api/'],
            ['GET', '/not/a/mocked/path/'],
            ['GET', 'https://us.i.posthog.com/flags/?v=2'],
        ]
        const mismatches: string[] = []
        for (const [method, url] of requests) {
            const expected = await answer(markers, method, url)
            const actual = await answer(router, method, url)
            if (actual !== expected) {
                mismatches.push(`${method} ${url}: msw ${expected}, router ${actual}`)
            }
        }
        expect(requests.length).toBeGreaterThan(300)
        expect(mismatches).toEqual([])
    })
})
