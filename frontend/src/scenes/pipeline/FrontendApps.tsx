import { LemonTable, LemonTableColumn } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { statusColumn, updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'

import { PipelineStage, ProductKey } from '~/types'

import { frontendAppsLogic } from './frontendAppsLogic'
import { NewButton } from './NewButton'
import { SiteApp } from './types'
import { appColumn, nameColumn, pipelinePluginBackedNodeMenuCommonItems } from './utils'

export function FrontendApps(): JSX.Element {
    const { loading, frontendApps } = useValues(frontendAppsLogic)
    const { toggleEnabled, loadPluginConfigs } = useActions(frontendAppsLogic)

    const shouldShowEmptyState = frontendApps.length === 0 && !loading

    return (
        <>
            <PageHeader
                caption="Extend your web app with custom functionality."
                buttons={<NewButton stage={PipelineStage.SiteApp} />}
            />
            <ProductIntroduction
                productName="Site apps"
                thingName="site app"
                productKey={ProductKey.SITE_APPS}
                description="Site apps allow you to add custom functionality to your website using PostHog."
                docsURL="https://posthog.com/docs/apps/pineapple-mode"
                actionElementOverride={<NewButton stage={PipelineStage.SiteApp} />}
                isEmpty={shouldShowEmptyState}
            />
            {!shouldShowEmptyState && (
                <>
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
