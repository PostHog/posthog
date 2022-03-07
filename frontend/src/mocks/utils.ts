import { rest } from 'msw'

type MockSignature = (
    req: Parameters<Parameters<typeof rest['get']>[1]>[0],
    res: Parameters<Parameters<typeof rest['get']>[1]>[1],
    ctx: Parameters<Parameters<typeof rest['get']>[1]>[2]
) => [number, any] | [number]
type Mocks = Partial<Record<keyof typeof rest, Record<string, MockSignature>>>

export const mocksToHandlers = (mocks: Mocks): ReturnType<typeof rest['get']>[] => {
    const response: ReturnType<typeof rest['get']>[] = []
    Object.entries(mocks).map(([method, mockHandlers]) => {
        Object.entries(mockHandlers).map(([path, handlerFunction]) => {
            response.push(
                (rest[method] as typeof rest['get'])(path, (req, res, ctx) => {
                    const [status, resp] = handlerFunction(req, res, ctx)
                    return res(ctx.status(status), ctx.json(resp ?? null))
                })
            )
        })
    })
    return response
}
