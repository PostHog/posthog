import { renderLayerGraphHtml } from './layerGraphHtml.mjs'
import { LAYERS, groupOf, layerOf } from './layers.mjs'

describe('layerGraphHtml.mjs', () => {
    it.each([
        [
            'a double quote that ends the attribute',
            'frontend/src/lib/components/Bad" onpointerover="alert(1)/index.tsx',
        ],
        ['an entity that the attribute decodes', 'frontend/src/lib/components/Bad&quot;/index.tsx'],
    ])('keeps a folder name with %s inside its graph node key', (_, file) => {
        const html = renderLayerGraphHtml({
            files: { [file]: { bytes: 100, staticImports: [] } },
            shellRoot: file,
            shellReach: new Map([[file, null]]),
            upward: [],
            layerOf,
            layers: LAYERS,
            opportunities: { lazyFolders: [], misplacedFiles: [], heavyHubs: [], kernelLeaks: [] },
        })
        document.documentElement.innerHTML = html
        new Function(html.match(/<script>([\s\S]*)<\/script>/)![1])()

        const nodes = document.querySelectorAll('#graph .node')
        expect(nodes).toHaveLength(1)
        expect(nodes[0].getAttribute('onpointerover')).toBeNull()
        expect(nodes[0].getAttribute('data-key')).toEqual(`${layerOf(file)}|${groupOf(file)}`)
    })
})
