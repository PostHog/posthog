import { rest, setupWorker } from 'msw'

// Default handlers ensure no request is unhandled by msw
export const worker = setupWorker(
    rest.get('*', (_, res, ctx) => res(ctx.status(500), ctx.text('No route registered'))),
    rest.post('*', (_, res, ctx) => res(ctx.status(500), ctx.text('No route registered'))),
    rest.put('*', (_, res, ctx) => res(ctx.status(500), ctx.text('No route registered'))),
    rest.delete('*', (_, res, ctx) => res(ctx.status(500), ctx.text('No route registered')))
)
