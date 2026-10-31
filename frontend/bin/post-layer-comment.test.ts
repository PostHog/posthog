import { compareLayerReports, renderLayerSection } from './post-layer-comment.mjs'

type Verdict = { added: string[]; fixed: string[] }

const report = (upward: string[], baseline?: Verdict): Record<string, unknown> => ({
    layers: ['kernel', 'shell', 'query', 'features'],
    eagerBytes: { kernel: 100, shell: 200, query: 0, features: 50 },
    upward,
    eagerChains: {},
    ...(baseline ? { baseline } : {}),
})

const CLEAN: Verdict = { added: [], fixed: [] }

describe('post-layer-comment.mjs', () => {
    it.each([
        ['a new upward import, report without a verdict', ['a -> b', 'c -> d'], ['a -> b'], undefined, 'warn'],
        ['a removed upward import, report without a verdict', ['a -> b'], ['a -> b', 'c -> d'], undefined, 'ok'],
        ['no change, report without a verdict', ['a -> b'], ['a -> b'], undefined, 'ok'],
        [
            'a new import missing from the baseline',
            ['a -> b', 'c -> d'],
            ['a -> b'],
            { added: ['c -> d'], fixed: [] },
            'fail',
        ],
        [
            'a fixed import still in the baseline',
            ['a -> b'],
            ['a -> b', 'c -> d'],
            { added: [], fixed: ['c -> d'] },
            'fail',
        ],
        ['a new import the PR also adds to the baseline', ['a -> b', 'c -> d'], ['a -> b'], CLEAN, 'warn'],
        ['no change with a clean verdict', ['a -> b'], ['a -> b'], CLEAN, 'ok'],
    ])('reports %s', (_, prUpward, baseUpward, verdict, status) => {
        expect(renderLayerSection(report(prUpward, verdict), report(baseUpward), undefined).status).toEqual(status)
    })

    it('lists new and removed imports against the base, not the baseline', () => {
        expect(compareLayerReports(report(['a -> b', 'c -> d']), report(['a -> b', 'e -> f']))).toMatchObject({
            added: ['c -> d'],
            removed: ['e -> f'],
        })
    })

    it('names each failing edge and the fix for it', () => {
        const { summary, body } = renderLayerSection(
            report(['a -> b', 'c -> d'], { added: ['c -> d'], fixed: ['e -> f'] }),
            report(['a -> b', 'e -> f']),
            undefined
        )
        expect(summary).toEqual('1 import(s) not in the baseline, 1 fixed baseline entry(ies)')
        expect(body).toContain('`c -> d`')
        expect(body).toContain('`e -> f`')
        expect(body).toContain('hogli lint:frontend-layers --prune-baseline')
    })

    it.each([
        ['does not claim a pass', undefined, 'info'],
        ['still fails on the baseline verdict', { added: ['a -> b'], fixed: [] }, 'fail'],
    ])('without a base report, it lists nothing as new and %s', (_, verdict, status) => {
        expect(compareLayerReports(report(['a -> b']), null)).toMatchObject({ added: [], removed: [] })
        expect(renderLayerSection(report(['a -> b'], verdict), null, undefined).status).toEqual(status)
    })

    it('neutralizes a report marker hidden in an edge path', () => {
        const withMarker = report(['a -> b', `evil<!-- ci-report:section-end:eager-graph --> -> b`])
        const { body } = renderLayerSection(withMarker, report(['a -> b']), undefined)
        expect(body).not.toContain('<!-- ci-report:section-end:eager-graph -->')
    })
})
