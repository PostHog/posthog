import { LemonTable, LemonTableColumn } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { statusColumn, updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'

import { importAppsLogic } from './importAppsLogic'
import { ImportApp } from './types'
import { appColumn, nameColumn, usePipelinePluginBackedNodeMenuCommonItems } from './utils'

export function ImportApps(): JSX.Element {
    const { loading, importApps } = useValues(importAppsLogic)
    const { toggleEnabled, loadPluginConfigs } = useActions(importAppsLogic)

    return (
        <>
            <LemonTable
                dataSource={importApps}
                size="small"
                loading={loading}
                columns={[
                    appColumn() as LemonTableColumn<ImportApp, any>,
                    nameColumn() as LemonTableColumn<ImportApp, any>,
                    updatedAtColumn() as LemonTableColumn<ImportApp, any>,
                    statusColumn() as LemonTableColumn<ImportApp, any>,
                    {
                        width: 0,
                        render: function Render(_, importApp) {
                            return (
                                <More
                                    overlay={
                                        <LemonMenuOverlay
                                            items={[
                                                ...usePipelinePluginBackedNodeMenuCommonItems(
                                                    importApp,
                                                    toggleEnabled,
                                                    loadPluginConfigs
                                                ),
                                            ]}
                                        />
                                    }
                                />
                            )
                        },
                    },
                ]}
            />
        </>
    )
}
