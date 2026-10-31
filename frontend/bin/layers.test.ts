import { compareWithBaseline, isUpward, layerOf } from './layers.mjs'

describe('layers.mjs', () => {
    it.each([
        ['frontend/src/queries/schema/schema-general.ts', 'kernel'],
        ['products/signals/frontend/generated/api.schemas.ts', 'kernel'],
        ['frontend/src/lib/utils/css-classes.ts', 'kernel'],
        ['frontend/src/lib/api.ts', 'kernel'],
        ['frontend/src/styles/global.scss', 'kernel'],
        ['frontend/src/queries/nodes/DataTable/DataTable.tsx', 'query'],
        ['frontend/src/layout/navigation-3000/Navigation.tsx', 'shell'],
        ['frontend/src/lib/logic/themeLogic.ts', 'shell'],
        ['frontend/src/lib/components/Command/Command.tsx', 'shell'],
        ['frontend/src/scenes/sceneLogic.tsx', 'shell'],
        ['frontend/src/scenes/dashboard/dashboardLogic.tsx', 'features'],
        ['products/signals/frontend/inbox/inboxTaskKickoffLogic.ts', 'features'],
        ['frontend/src/a-folder-nobody-has-mapped/thing.ts', 'features'],
    ])('puts %s in the %s layer', (file, layer) => {
        expect(layerOf(file)).toEqual(layer)
    })

    it.each([
        ['frontend/src/layout/Navigation.tsx', 'frontend/src/scenes/max/maxLogic.tsx', true],
        ['frontend/src/layout/Navigation.tsx', 'frontend/src/queries/nodes/DataTable/DataTable.tsx', true],
        ['frontend/src/scenes/max/maxLogic.tsx', 'frontend/src/layout/Navigation.tsx', false],
        ['frontend/src/layout/Navigation.tsx', 'frontend/src/layout/panel-layout/PanelLayout.tsx', false],
    ])('%s -> %s is upward: %s', (from, to, upward) => {
        expect(isUpward(from, to)).toEqual(upward)
    })

    const NEW = 'frontend/src/layout/Navigation.tsx -> frontend/src/scenes/max/maxLogic.tsx'
    const KEPT = 'frontend/src/lib/components/Command/Command.tsx -> frontend/src/scenes/max/maxLogic.tsx'
    const FIXED = 'frontend/src/models/thing.ts -> frontend/src/scenes/dashboard/dashboardLogic.tsx'

    const PRUNE_HINT = `1 baseline entries are fixed. Run \`hogli lint:frontend-layers --prune-baseline\` to drop them:\n  ${FIXED}`

    it.each([
        ['an exact match passes', [KEPT], [KEPT], { added: [], fixed: [], failed: false, pruneHint: null }],
        ['a new edge fails', [KEPT, NEW], [KEPT], { added: [NEW], fixed: [], failed: true, pruneHint: null }],
        [
            'a fixed edge fails with the prune hint',
            [KEPT],
            [KEPT, FIXED],
            { added: [], fixed: [FIXED], failed: true, pruneHint: PRUNE_HINT },
        ],
    ])('compares with the baseline: %s', (_, current, baseline, expected) => {
        expect(compareWithBaseline(current, baseline)).toEqual(expected)
    })
})
