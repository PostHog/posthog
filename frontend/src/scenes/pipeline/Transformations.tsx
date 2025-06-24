import { LemonTable, LemonTableColumn, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { statusColumn, updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { urls } from 'scenes/urls'

import { PipelineNodeTab, PipelineStage, ProductKey } from '~/types'

import { AppMetricSparkLine } from './AppMetricSparkLine'
import { TRANSFORMATION_TYPES } from './destinations/constants'
import { Destinations } from './destinations/Destinations'
import { NewButton } from './NewButton'
import { pipelineAccessLogic } from './pipelineAccessLogic'
import { pipelineTransformationsLogic } from './transformationsLogic'
import { Transformation } from './types'
import { appColumn, nameColumn, usePipelinePluginBackedNodeMenuCommonItems } from './utils'

export function Transformations(): JSX.Element {
    const { sortedTransformations, loading } = useValues(pipelineTransformationsLogic)

    const shouldShowEmptyState = sortedTransformations.length === 0 && !loading

    return (
        <>
            <PageHeader
                caption="Transform your incoming events before they are stored in PostHog or sent on to Destinations."
                buttons={<NewButton stage={PipelineStage.Transformation} />}
            />
            <ProductIntroduction
                productName="Pipeline transformations"
                thingName="transformation"
                productKey={ProductKey.PIPELINE_TRANSFORMATIONS}
                description="Pipeline transformations allow you to enrich your data with additional information, such as geolocation."
                docsURL="https://posthog.com/docs/cdp"
                actionElementOverride={<NewButton stage={PipelineStage.Transformation} />}
                isEmpty={shouldShowEmptyState}
            />

            <Destinations types={TRANSFORMATION_TYPES} />
        </>
    )
}

export function TransformationsTable({ inOverview = false }: { inOverview?: boolean }): JSX.Element {
    const { loading, sortedTransformations, sortedEnabledTransformations } = useValues(pipelineTransformationsLogic)

    return (
        <>
            <LemonTable
                dataSource={inOverview ? sortedEnabledTransformations : sortedTransformations}
                size="small"
                loading={loading}
                columns={[
                    {
                        title: '',
                        key: 'order',
                        width: 0,
                        sticky: true,
                        render: function RenderOrdering(_, transformation) {
                            if (!transformation.enabled) {
                                return null
                            }
                            // We can't use pluginConfig.order directly as it's not nicely set for everything,
                            // e.g. geoIP, disabled plugins, especially if we disable them via django admin
                            return sortedEnabledTransformations.findIndex((t) => t.id === transformation.id) + 1
                        },
                    },
                    appColumn() as LemonTableColumn<Transformation, any>,
                    nameColumn() as LemonTableColumn<Transformation, any>,
                    {
                        title: 'Last 7 days',
                        render: function RenderSuccessRate(_, transformation) {
                            return (
                                <Link
                                    to={urls.pipelineNode(
                                        PipelineStage.Transformation,
                                        transformation.id,
                                        PipelineNodeTab.Metrics
                                    )}
                                >
                                    <AppMetricSparkLine pipelineNode={transformation} />
                                </Link>
                            )
                        },
                    },
                    updatedAtColumn() as LemonTableColumn<Transformation, any>,
                    statusColumn() as LemonTableColumn<Transformation, any>,
                    {
                        width: 0,
                        render: function Render(_, transformation) {
                            return (
                                <More
                                    overlay={
                                        <TransformationsMoreOverlay
                                            transformation={transformation}
                                            inOverview={inOverview}
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

export const TransformationsMoreOverlay = ({
    transformation,
    inOverview = false,
}: {
    transformation: Transformation
    inOverview?: boolean
}): JSX.Element => {
    const { canConfigurePlugins } = useValues(pipelineAccessLogic)
    const { toggleEnabled, loadPluginConfigs, openReorderModal } = useActions(pipelineTransformationsLogic)
    const { sortedEnabledTransformations } = useValues(pipelineTransformationsLogic)

    return (
        <LemonMenuOverlay
            items={[
                ...(!inOverview && transformation.enabled && sortedEnabledTransformations.length > 1
                    ? [
                          {
                              label: 'Reorder apps',
                              onClick: openReorderModal,
                              disabledReason: canConfigurePlugins
                                  ? undefined
                                  : 'You do not have permission to reorder apps.',
                          },
                      ]
                    : []),
                ...usePipelinePluginBackedNodeMenuCommonItems(
                    transformation,
                    toggleEnabled,
                    loadPluginConfigs,
                    inOverview
                ),
            ]}
        />
    )
}
