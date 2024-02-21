import { LemonTable, LemonTableColumn } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { statusColumn, updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { importAppsLogic } from './importAppsLogic'
import { ImportApp } from './types'
import { appColumn, nameColumn, pipelinePluginBackedNodeMenuCommonItems } from './utils'

export function ImportApps(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.PIPELINE_UI]) {
        return <p>Pipeline 3000 not available yet</p>
    }
    const { loading, importApps } = useValues(importAppsLogic)
    const { toggleEnabled, loadPluginConfigs } = useActions(importAppsLogic)

    return (
        <>
            <LemonTable
                dataSource={importApps}
                size="small"
                loading={loading}
                columns={[
                    nameColumn() as LemonTableColumn<ImportApp, any>,
                    appColumn() as LemonTableColumn<ImportApp, any>,
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
                                                ...pipelinePluginBackedNodeMenuCommonItems(
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
