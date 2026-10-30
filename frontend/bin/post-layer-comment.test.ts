import { compareLayerReports, renderLayerSection } from './post-layer-comment.mjs'

const report = (upward: string[]): Record<string, unknown> => ({
    layers: ['kernel', 'shell', 'query', 'features'],
    eagerBytes: { kernel: 100, shell: 200, query: 0, features: 50 },
    upward,
    eagerChains: {},
})

describe('post-layer-comment.mjs', () => {
    it.each([
        ['a new upward import', ['a -> b', 'c -> d'], ['a -> b'], ['c -> d'], [], 'warn'],
        ['a removed upward import', ['a -> b'], ['a -> b', 'c -> d'], [], ['c -> d'], 'ok'],
        ['no change', ['a -> b'], ['a -> b'], [], [], 'ok'],
    ])('reports %s against the base, not the baseline', (_, prUpward, baseUpward, added, removed, status) => {
        expect(compareLayerReports(report(prUpward), report(baseUpward))).toMatchObject({ added, removed })
        expect(renderLayerSection(report(prUpward), report(baseUpward), undefined).status).toEqual(status)
    })

    it('lists nothing as new when the base has no report', () => {
        expect(compareLayerReports(report(['a -> b']), null)).toMatchObject({ added: [], removed: [] })
    })
})
