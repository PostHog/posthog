import { LemonTable, LemonTableColumn } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { FEATURE_FLAGS } from 'lib/constants'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { statusColumn, updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { PipelineStage, ProductKey } from '~/types'

import { frontendAppsLogic } from './frontendAppsLogic'
import { NewButton } from './NewButton'
import { SiteApp } from './types'
import { appColumn, nameColumn, pipelinePluginBackedNodeMenuCommonItems } from './utils'

export function FrontendApps(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.PIPELINE_UI]) {
        return <p>Pipeline 3000 not available yet</p>
    }
    const { loading, frontendApps, shouldShowProductIntroduction } = useValues(frontendAppsLogic)
    const { toggleEnabled, loadPluginConfigs } = useActions(frontendAppsLogic)

    const shouldShowEmptyState = frontendApps.length === 0

    return (
        <>
            {(shouldShowEmptyState || shouldShowProductIntroduction) && (
                <ProductIntroduction
                    productName="Site apps"
                    thingName="site app"
                    productKey={ProductKey.SITE_APPS}
                    description="Site apps allow you to ..."
                    docsURL="https://posthog.com/docs/apps/pineapple-mode"
                    actionElementOverride={<NewButton stage={PipelineStage.SiteApp} />}
                    isEmpty={true}
                />
            )}
            {!shouldShowEmptyState && (
                <>
                    <LemonTable
                        dataSource={frontendApps}
                        size="small"
                        loading={loading}
                        columns={[
                            nameColumn() as LemonTableColumn<SiteApp, any>,
                            appColumn() as LemonTableColumn<SiteApp, any>,
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
