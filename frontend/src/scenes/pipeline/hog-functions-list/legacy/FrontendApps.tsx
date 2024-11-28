// This code shows the old legacy site apps while we haven't migrated everyone over.

import { LemonTable, LemonTableColumn } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { statusColumn, updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'

import { SiteApp } from '../../types'
import { appColumn, nameColumn, pipelinePluginBackedNodeMenuCommonItems } from '../../utils'
import { frontendAppsLogic } from './frontendAppsLogic'

export function FrontendApps(): JSX.Element {
    const { loading, frontendApps } = useValues(frontendAppsLogic)
    const { toggleEnabled, loadPluginConfigs } = useActions(frontendAppsLogic)
    return (
        <>
            {frontendApps.length > 0 && (
                <>
                    <h2 className="mt-4">Legacy site apps</h2>
                    <p>These site apps are using an older system. You may migrate at your leasure.</p>
                    <LemonTable
                        dataSource={frontendApps}
                        size="small"
                        loading={loading}
                        columns={[
                            appColumn() as LemonTableColumn<SiteApp, any>,
                            nameColumn() as LemonTableColumn<SiteApp, any>,
                            updatedAtColumn() as LemonTableColumn<SiteApp, any>,
                            statusColumn() as LemonTableColumn<SiteApp, any>,
                            {
                                width: 0,
                                render: function Render(_, frontendApp) {
                                    return (
                                        <More
                                            overlay={
                                                <LemonMenuOverlay
                                                    items={[
                                                        ...pipelinePluginBackedNodeMenuCommonItems(
                                                            frontendApp,
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
            )}
        </>
    )
}
