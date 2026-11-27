import path from 'path'

import { moduleGraphPlugin } from './vite-module-graph-plugin'

describe('moduleGraphPlugin', () => {
    it('lists an importer as dynamic only when it never imports the module statically', () => {
        const repoRoot = path.resolve(__dirname, '../../../..')
        const preview = 'common/storybook/.storybook/preview.tsx'
        const app = 'frontend/src/scenes/App.tsx'
        const experiment = 'frontend/src/scenes/experiments/Experiment.tsx'
        const dashboard = 'frontend/src/scenes/dashboard/Dashboard.tsx'
        const importsByModule: Record<string, { importers: string[]; dynamicImporters: string[] }> = {
            [preview]: { importers: [], dynamicImporters: [] },
            [app]: { importers: [preview], dynamicImporters: [] },
            [experiment]: { importers: [app], dynamicImporters: [app] },
            [dashboard]: { importers: [], dynamicImporters: [app] },
        }
        const toId = (name: string): string => path.join(repoRoot, name)

        let emitted = ''
        const bundleContext = {
            getModuleIds: () => Object.keys(importsByModule).map(toId).values(),
            getModuleInfo: (id: string) => {
                const { importers, dynamicImporters } = importsByModule[path.relative(repoRoot, id)]
                return { importers: importers.map(toId), dynamicImporters: dynamicImporters.map(toId) }
            },
            emitFile: ({ source }: { source: string }) => {
                emitted = source
            },
        }
        jest.spyOn(console, 'log').mockImplementation(() => {})

        const generateBundle = moduleGraphPlugin(repoRoot).generateBundle as unknown as (
            this: typeof bundleContext
        ) => void
        generateBundle.call(bundleContext)

        expect(JSON.parse(emitted).modules).toEqual([
            { name: preview, reasons: [], dynamicReasons: [] },
            { name: app, reasons: [preview], dynamicReasons: [] },
            { name: experiment, reasons: [app], dynamicReasons: [] },
            { name: dashboard, reasons: [app], dynamicReasons: [app] },
        ])
    })
})
