import { rest } from 'msw'

export type MockSignature =
    | ((
          req: Parameters<Parameters<(typeof rest)['get']>[1]>[0],
          res: Parameters<Parameters<(typeof rest)['get']>[1]>[1],
          ctx: Parameters<Parameters<(typeof rest)['get']>[1]>[2]
      ) => [number, any] | [number])
    | Record<string, any>
export type Mocks = Partial<Record<keyof typeof rest, Record<string, MockSignature>>>

export const mocksToHandlers = (mocks: Mocks): ReturnType<(typeof rest)['get']>[] => {
    const response: ReturnType<(typeof rest)['get']>[] = []
    Object.entries(mocks).map(([method, mockHandlers]) => {
        Object.entries(mockHandlers).map(([path, handler]) => {
            const pathWithoutTrailingSlash = path.replace(/\/$/, '')
            response.push(
                (rest[method] as (typeof rest)['get'])(pathWithoutTrailingSlash, async (req, res, ctx) => {
                    // We currently support a few ways to specify a mock response:
                    // 1. A function that returns a tuple of [status, body]
                    // 2. A function that returns a tuple of [status]
                    // 3. A function that returns undefined. This represents that a network error has occured
                    // 4. A function that returns an MSW response
                    // 5. A JSON serializable object that will be returned as the response body
                    if (typeof handler === 'function') {
                        const response = await handler(req, res, ctx)
                        if (Array.isArray(response)) {
                            const responseArray = response
                            if (responseArray.length === 2 && typeof responseArray[0] === 'number') {
                                return res(ctx.status(responseArray[0]), ctx.json(responseArray[1] ?? null))
                            }
                            return res(...responseArray)
                        } else if (!response) {
                            return res()
                        }
                        return response
                    }
                    return res(ctx.json(handler ?? null))
                })
            )
        })
    })
    return response
}
