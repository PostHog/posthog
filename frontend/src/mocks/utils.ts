import { http, HttpResponse, type DefaultBodyType, type HttpHandler, type HttpResponseResolver } from 'msw'

export const HTTP_METHODS = ['get', 'post', 'put', 'patch', 'delete', 'options'] as const
export type HttpMethod = (typeof HTTP_METHODS)[number]

// The resolver argument MSW v2 passes to a handler: `{ request, params, cookies, requestId }`.
export type MockResolverInfo = Parameters<HttpResponseResolver>[0]

// What a mock resolves to:
// 1. A `[status, body]` tuple
// 2. A `[status]` tuple
// 3. `undefined`/`null` — models a network error
// 4. A `Response`/`HttpResponse`
// 5. Any other value — returned as a JSON body
type MockResult = Response | [number, DefaultBodyType?] | DefaultBodyType | null | undefined

// A v2-shaped resolver: `({ request, params, ... }) => MockResult`.
type V2Resolver = (info: MockResolverInfo) => MockResult | Promise<MockResult>
// A legacy MSW v1-shaped resolver: `(req, res, ctx) => MockResult`. Typed loosely on purpose — this
// is a back-compat shim for test/story authors, not a faithful re-implementation of the v1 API.
type V1Resolver = (req: any, res: any, ctx: any) => MockResult | Promise<MockResult>

export type MockSignature = V2Resolver | V1Resolver | Record<string, any> | any[]
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
        // A bare empty return models a network error (the v1 `res()` behavior).
        return HttpResponse.error()
    }
    return HttpResponse.json(result)
}

// ---------------------------------------------------------------------------
// Back-compat shim for the legacy MSW v1 `(req, res, ctx)` resolver signature.
//
// In v1, resolvers received a parsed request (`req.url` was a `URL`, `req.body`
// was the already-parsed body, `req.params` were the path params) plus `res`
// and `ctx` helpers, and returned `res(ctx.status(s), ctx.json(b), ctx.set(h))`.
//
// In v2, resolvers receive `{ request, params }`, must `await request.json()`,
// and return an `HttpResponse`. This shim adapts a v1 resolver onto the v2
// callback so existing inline mocks keep working without being rewritten.
//
// Detection: a v1 resolver declares >= 2 positional params (`req, res, ctx`),
// whereas a v2 resolver takes a single destructured `{ request }` object.
// ---------------------------------------------------------------------------

const isLegacyResolver = (handler: V2Resolver | V1Resolver): handler is V1Resolver => handler.length >= 2

// Models the accumulating "transformers" that v1 `ctx.*` helpers produced and
// `res(...)` combined. Each helper returns a partial patch; `res` folds them.
interface ResponsePatch {
    status?: number
    headers?: Record<string, string>
    // `body` is a JSON value, `rawBody` a string (from ctx.text). Last write wins.
    body?: DefaultBodyType
    rawBody?: string
    delayMs?: number
}

const ctxShim = {
    status: (status: number): ResponsePatch => ({ status }),
    json: (body: DefaultBodyType): ResponsePatch => ({ body }),
    text: (rawBody: string): ResponsePatch => ({ rawBody }),
    set: (headersOrName: Record<string, string> | string, maybeValue?: string): ResponsePatch =>
        typeof headersOrName === 'string'
            ? { headers: { [headersOrName]: maybeValue ?? '' } }
            : { headers: { ...headersOrName } },
    // v1 `ctx.delay()` — we don't actually delay in the shim (tests/stories don't
    // depend on real timing), we just swallow it so the call is a no-op patch.
    delay: (): ResponsePatch => ({}),
}

// The v1 `res(...transformers)` helper: fold the patches into a single Response.
const resShim = (...patches: ResponsePatch[]): Response => {
    const merged: ResponsePatch = {}
    for (const patch of patches) {
        Object.assign(merged, patch)
        // Merge headers rather than overwrite, so multiple ctx.set() calls stack.
        if (patch.headers) {
            merged.headers = { ...merged.headers, ...patch.headers }
        }
    }
    const init: ResponseInit = { status: merged.status, headers: merged.headers }
    if (merged.rawBody !== undefined) {
        return new HttpResponse(merged.rawBody, init)
    }
    // `res()` with no body, or only status/headers, models an empty response.
    if (merged.body === undefined && merged.rawBody === undefined && patches.length === 0) {
        return HttpResponse.error()
    }
    return HttpResponse.json(merged.body ?? null, init)
}

// Build the v1-style `req` from the v2 `{ request, params }` info. We pre-read
// the body so both the sync `req.body` accessor and `req.json()`/`req.text()`
// keep working the way v1 callers expect.
const buildLegacyReq = async (info: MockResolverInfo): Promise<any> => {
    const { request, params } = info
    const url = new URL(request.url)

    let parsedBody: any
    let rawText = ''
    try {
        rawText = await request.clone().text()
        parsedBody = rawText ? JSON.parse(rawText) : undefined
    } catch {
        // Non-JSON or empty body — leave `body` undefined, expose raw text below.
        parsedBody = undefined
    }

    return {
        url,
        params,
        // v1 exposed the already-parsed body synchronously.
        body: parsedBody,
        headers: request.headers,
        // v1 `req.json()` / `req.text()` were async; preserve that shape.
        json: async () => (rawText ? JSON.parse(rawText) : parsedBody),
        text: async () => rawText,
        // Occasionally used: `req.get(headerName)`.
        get: (name: string) => request.headers.get(name),
        method: request.method,
    }
}

const runLegacyResolver = async (handler: V1Resolver, info: MockResolverInfo): Promise<MockResult> => {
    const req = await buildLegacyReq(info)
    // `res` and `ctx` are the shims defined above.
    return handler(req, resShim, ctxShim)
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
                            // Back-compat: a `(req, res, ctx)` resolver is adapted onto the v2
                            // callback. A `({ request })` resolver runs through the v2 path.
                            const result = isLegacyResolver(handler as V2Resolver | V1Resolver)
                                ? await runLegacyResolver(handler as V1Resolver, info)
                                : await (handler as V2Resolver)(info)
                            // A legacy resolver that already returned via `res(ctx...)` produces a
                            // `Response`, which `toResponse` passes straight through.
                            return toResponse(result)
                        }
                        return HttpResponse.json((handler as DefaultBodyType) ?? null)
                    })
                )
            })
        })
    return handlers
}
