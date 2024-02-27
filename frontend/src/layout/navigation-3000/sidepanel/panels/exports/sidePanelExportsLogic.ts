import { afterMount, connect, kea, path } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { exportsLogic } from '~/layout/navigation-3000/sidepanel/panels/exports/exportsLogic'
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
            ['exports'],
        ],
        actions: [sidePanelStateLogic, ['openSidePanel'], exportsLogic, ['loadExports']],
    }),
    afterMount(({ actions }) => {
        actions.loadExports()
    }),
])
