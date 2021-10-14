import { rest, setupWorker } from 'msw'

// Default handlers ensure no request is unhandled by msw
export const worker = setupWorker(
    // For /e/ let's just return a 200, we're not interested in mocking this any further
    rest.post('/e/', (_, res, ctx) => res(ctx.status(200))),

    // For everything else, require something explicit to be set
    rest.get('/api/*', (_, res, ctx) => res(ctx.status(500), ctx.text('No route registered'))),
    rest.post('/api/*', (_, res, ctx) => res(ctx.status(500), ctx.text('No route registered'))),
    rest.put('/api/*', (_, res, ctx) => res(ctx.status(500), ctx.text('No route registered'))),
    rest.delete('/api/*', (_, res, ctx) => res(ctx.status(500), ctx.text('No route registered')))
)
