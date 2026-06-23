import { http, HttpResponse, type DefaultBodyType, type HttpHandler, type HttpResponseResolver } from 'msw'

export const HTTP_METHODS = ['get', 'post', 'put', 'patch', 'delete', 'options'] as const
export type HttpMethod = (typeof HTTP_METHODS)[number]

// The resolver argument MSW v2 passes to a handler: `{ request, params, cookies, requestId }`.
export type MockResolverInfo = Parameters<HttpResponseResolver>[0]

// What a mock resolves to:
// 1. A `[status, body]` tuple
// 2. A `[status]` tuple
// 3. `undefined`/`null` — an empty 200 (matches v1's `res()`); for a real network error
//    return `HttpResponse.error()` explicitly
// 4. A `Response`/`HttpResponse`
// 5. Any other value — returned as a JSON body
type MockResult = Response | [number, DefaultBodyType?] | DefaultBodyType | null | undefined

export type MockSignature = ((info: MockResolverInfo) => MockResult | Promise<MockResult>) | Record<string, any> | any[]
export type Mocks = Partial<Record<HttpMethod, Record<string, MockSignature>>>

const toResponse = (result: MockResult): Response => {
    if (result instanceof Response) {
        return result
    }
    if (Array.isArray(result)) {
        if (result.length === 2 && typeof result[0] === 'number') {
            return HttpResponse.json(result[1] ?? null, { status: result[0] })
        }
        if (result.length === 1 && typeof result[0] === 'number') {
            return new HttpResponse(null, { status: result[0] })
        }
        // Any other array is a JSON array body.
        return HttpResponse.json(result)
    }
    if (result == null) {
        // A bare empty return is an empty 200, matching v1's `res()`. This is the fall-through
        // for handlers with conditional branches and no final else (e.g. a query mock that only
        // covers some kinds) — it must NOT be a network error, or apiStatusLogic flips the whole
        // app into the "trouble connecting to the server" banner. Return HttpResponse.error()
        // explicitly to model a real network failure.
        return new HttpResponse(null, { status: 200 })
    }
    return HttpResponse.json(result)
}

export const mocksToHandlers = (mocks: Mocks): HttpHandler[] => {
    const handlers: HttpHandler[] = []
    Object.entries(mocks)
        .filter((entry): entry is [HttpMethod, Record<string, MockSignature>] => !!entry[1])
        .forEach(([method, mockHandlers]) => {
            Object.entries(mockHandlers).forEach(([path, handler]) => {
                const pathWithoutTrailingSlash = path.replace(/\/$/, '')
                handlers.push(
                    (http[method] as (typeof http)['get'])(pathWithoutTrailingSlash, async (info) => {
                        // A function handler returns one of the MockResult forms (sync or async);
                        // any other value is a static JSON body (arrays serialized as-is, matching v1).
                        if (typeof handler === 'function') {
                            return toResponse(await handler(info))
                        }
                        return HttpResponse.json((handler as DefaultBodyType) ?? null)
                    })
                )
            })
        })
    return handlers
}
