import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { ExportedAssetType, SidePanelTab } from '~/types'

import { activityForSceneLogic } from '../activity/activityForSceneLogic'
import type { sidePanelExportsLogicType } from './sidePanelExportsLogicType'

export const sidePanelExportsLogic = kea<sidePanelExportsLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelExportsLogic']),
    actions({
        loadExports: true,
        addExport: true,
    }),
    connect({
        values: [featureFlagLogic, ['featureFlags'], activityForSceneLogic, ['sceneActivityFilters']],
        actions: [sidePanelStateLogic, ['openSidePanel']],
    }),
    reducers({
        exports: [
            [] as ExportedAssetType[],
            {
                loadExportsSuccess: (_, { exports }) => exports,
            },
        ],
    }),
    listeners(({ actions }) => ({
        addExport: () => {
            actions.openSidePanel(SidePanelTab.Exports)
            actions.loadExports()
        },
    })),
    loaders(() => ({
        exports: [
            [] as ExportedAssetType[],
            {
                loadExports: async (_, breakpoint) => {
                    await breakpoint(100)
                    const response = await api.exports.list()

                    breakpoint()

                    return response.results
                },
            },
        ],
    })),
])
