import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { TriggerExportProps } from 'lib/components/ExportButton/exporter'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { ExportedAssetType, SidePanelTab } from '~/types'

import type { exportsLogicType } from './exportslogicType'

export const exportsLogic = kea<exportsLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'exportsLogic']),

    actions({
        loadExports: true,
        createExport: (exportData: TriggerExportProps) => ({ exportData }),
        checkExportStatus: (exportedAsset: ExportedAssetType) => ({ exportedAsset }),
    }),

    connect({
        values: [featureFlagLogic, ['featureFlags']],
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
        createExport: async ({ exportData }) => {
            await api.exports.create({
                export_format: exportData.export_format,
                dashboard: exportData.dashboard,
                insight: exportData.insight,
                export_context: exportData.export_context,
                expires_after: dayjs().add(6, 'hour').toJSON(),
            })
            actions.openSidePanel(SidePanelTab.Exports)
            actions.loadExports()
        },
        checkExportStatus: async ({ exportedAsset }) => {
            const updatedAsset = await api.exports.get(exportedAsset.id)
            if (updatedAsset.has_content) {
                actions.loadExports()
            }
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
