import { afterMount, connect, kea, path } from 'kea'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'

import type { sidePanelExportsLogicType } from './sidePanelExportsLogicType'

export const sidePanelExportsLogic = kea<sidePanelExportsLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelExportsLogic']),
    connect(() => ({
        values: [exportsLogic, ['exports', 'freshUndownloadedExports']],
        actions: [sidePanelStateLogic, ['openSidePanel'], exportsLogic, ['loadExports', 'removeFresh']],
    })),
    afterMount(({ actions }) => {
        actions.loadExports()
    }),
])
