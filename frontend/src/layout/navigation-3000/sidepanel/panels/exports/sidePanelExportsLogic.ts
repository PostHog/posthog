import { afterMount, connect, kea, path } from 'kea'
import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'

import { activityForSceneLogic } from '../activity/activityForSceneLogic'
import type { sidePanelExportsLogicType } from './sidePanelExportsLogicType'

export const sidePanelExportsLogic = kea<sidePanelExportsLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelExportsLogic']),
    connect({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            activityForSceneLogic,
            ['sceneActivityFilters'],
            exportsLogic,
            ['exports', 'freshUndownloadedExports'],
        ],
        actions: [sidePanelStateLogic, ['openSidePanel'], exportsLogic, ['loadExports', 'removeFresh']],
    }),
    afterMount(({ actions }) => {
        actions.loadExports()
    }),
])
