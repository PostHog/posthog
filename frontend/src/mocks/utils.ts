import { rest } from 'msw'

export type MockSignature =
    | ((
          req: Parameters<Parameters<typeof rest['get']>[1]>[0],
          res: Parameters<Parameters<typeof rest['get']>[1]>[1],
          ctx: Parameters<Parameters<typeof rest['get']>[1]>[2]
      ) => [number, any] | [number])
    | Record<string, any>
export type Mocks = Partial<Record<keyof typeof rest, Record<string, MockSignature>>>

export const mocksToHandlers = (mocks: Mocks): ReturnType<typeof rest['get']>[] => {
    const response: ReturnType<typeof rest['get']>[] = []
    Object.entries(mocks).map(([method, mockHandlers]) => {
        Object.entries(mockHandlers).map(([path, handler]) => {
            response.push(
                (rest[method] as typeof rest['get'])(path, async (req, res, ctx) => {
                    if (typeof handler === 'function') {
                        const responseArray = handler(req, res, ctx)
                        if (responseArray.length === 2 && typeof responseArray[0] === 'number') {
                            return res(ctx.status(responseArray[0]), ctx.json(responseArray[1] ?? null))
                        }
                        return res(...responseArray)
                    } else {
                        return res(ctx.json(handler ?? null))
                    }
                })
            )
        })
    })
    return response
}
