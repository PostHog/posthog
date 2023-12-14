import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { batchExportsListLogic } from 'scenes/batch_exports/batchExportsListLogic'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'

import { PluginConfigTypeNew } from '~/types'

import type { exportsUnsubscribeModalLogicType } from './exportsUnsubscribeModalLogicType'

export const exportsUnsubscribeModalLogic = kea<exportsUnsubscribeModalLogicType>([
    path(['scenes', 'pipeline', 'exportsUnsubscribeModalLogic']),
    connect({ values: [pluginsLogic, ['plugins'], batchExportsListLogic, ['batchExportConfigs']] }),
    actions({
        openModal: true,
        closeModal: true,
    }),
    loaders(() => ({
        pluginConfigsToDisable: [
            [] as PluginConfigTypeNew[],
            {
                loadPluginConfigs: async () => {
                    return await api.get<PluginConfigTypeNew[]>(
                        `api/organizations/@current/plugins/exports_unsubscribe_configs`
                    )
                },
            },
        ],
    })),
    selectors({
        loading: [
            (s) => [s.batchExportsLoading, s.pluginConfigsToDisableLoading],
            (batchExportsLoading, pluginConfigsLoading) => batchExportsLoading || pluginConfigsLoading,
        ],
        unsubscribeDisabled: [
            (s) => [s.pluginConfigsToDisable, s.batchExports],
            (pluginConfigs, batchExports) => pluginConfigs || batchExports,
        ],
    }),
    reducers({
        modalOpen: [
            false,
            {
                openModal: () => true,
                closeModal: () => false,
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadPluginConfigs()
    }),
])
