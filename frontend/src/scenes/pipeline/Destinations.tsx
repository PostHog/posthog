import { LemonTable, LemonTableColumn, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { FEATURE_FLAGS } from 'lib/constants'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown/LemonMarkdown'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { Sparkline, SparklineTimeSeries } from 'lib/lemon-ui/Sparkline'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { urls } from 'scenes/urls'

import { PipelineNodeTab, PipelineStage, ProductKey } from '~/types'

import { pipelineDestinationsLogic } from './destinationsLogic'
import { NewButton } from './NewButton'
import { pipelineNodeMetricsLogic } from './pipelineNodeMetricsLogic'
import { Destination, PipelineBackend } from './types'
import { RenderApp } from './utils'

export function Destinations(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.PIPELINE_UI]) {
        return <p>Pipeline 3000 not available yet</p>
    }
    const { enabledPluginConfigs, disabledPluginConfigs, shouldShowProductIntroduction } =
        useValues(pipelineDestinationsLogic)

    const shouldShowEmptyState = enabledPluginConfigs.length === 0 && disabledPluginConfigs.length === 0

    return (
        <>
            {(shouldShowEmptyState || shouldShowProductIntroduction) && (
                <ProductIntroduction
                    productName="Pipeline destinations"
                    thingName="destination"
                    productKey={ProductKey.PIPELINE_DESTINATIONS}
                    description="Pipeline destinations allow you to export data outside of PostHog, such as webhooks to Slack."
                    docsURL="https://posthog.com/docs/cdp"
                    actionElementOverride={<NewButton stage={PipelineStage.Destination} />}
                    isEmpty={true}
                />
            )}
            <DestinationsTable />
        </>
    )
}

function DestinationsTable(): JSX.Element {
    const { loading, destinations, canConfigurePlugins } = useValues(pipelineDestinationsLogic)
    const { toggleEnabled, loadPluginConfigs } = useActions(pipelineDestinationsLogic)

    return (
        <>
            <LemonTable
                dataSource={destinations}
                size="xs"
                loading={loading}
                columns={[
                    {
                        title: 'Name',
                        sticky: true,
                        render: function RenderPluginName(_, destination) {
                            return (
                                <>
                                    <Tooltip title="Click to update configuration, view metrics, and more">
                                        <Link
                                            to={urls.pipelineStep(
                                                PipelineStage.Destination,
                                                destination.id,
                                                PipelineNodeTab.Configuration
                                            )}
                                        >
                                            <span className="row-name">{destination.name}</span>
                                        </Link>
                                    </Tooltip>
                                    {destination.description && (
                                        <LemonMarkdown className="row-description" lowKeyHeadings>
                                            {destination.description}
                                        </LemonMarkdown>
                                    )}
                                </>
                            )
                        },
                    },
                    {
                        title: 'App',
                        render: function RenderAppInfo(_, destination) {
                            if (destination.backend === 'plugin') {
                                return <RenderApp plugin={destination.plugin} />
                            }
                            return <></> // TODO: batch export
                        },
                    },
                    {
                        title: 'Frequency',
                        render: function RenderFrequency(_, destination) {
                            return destination.frequency
                        },
                    },
                    {
                        title: 'Success rate',
                        render: function RenderSuccessRate(_, destination) {
                            return <DestinationSparkLine destination={destination} />
                        },
                    },
                    updatedAtColumn() as LemonTableColumn<Destination, any>,
                    {
                        title: 'Status',
                        render: function RenderStatus(_, destination) {
                            return (
                                <>
                                    {destination.enabled ? (
                                        <LemonTag type="success" className="uppercase">
                                            Active
                                        </LemonTag>
                                    ) : (
                                        <LemonTag type="default" className="uppercase">
                                            Paused
                                        </LemonTag>
                                    )}
                                </>
                            )
                        },
                    },
                    {
                        width: 0,
                        render: function Render(_, destination) {
                            return (
                                <More
                                    overlay={
                                        <LemonMenuOverlay
                                            items={[
                                                {
                                                    label: destination.enabled
                                                        ? 'Pause destination'
                                                        : 'Unpause destination',
                                                    onClick: () => toggleEnabled(destination, !destination.enabled),
                                                    disabledReason: canConfigurePlugins
                                                        ? undefined
                                                        : 'You do not have permission to enable/disable destinations.',
                                                },
                                                {
                                                    label: canConfigurePlugins
                                                        ? 'Edit configuration'
                                                        : 'View configuration',
                                                    to: urls.pipelineStep(
                                                        PipelineStage.Destination,
                                                        destination.id,
                                                        PipelineNodeTab.Configuration
                                                    ),
                                                },
                                                {
                                                    label: 'View metrics',
                                                    to: urls.pipelineStep(
                                                        PipelineStage.Destination,
                                                        destination.id,
                                                        PipelineNodeTab.Metrics
                                                    ),
                                                },
                                                {
                                                    label: 'View logs',
                                                    to: urls.pipelineStep(
                                                        PipelineStage.Destination,
                                                        destination.id,
                                                        PipelineNodeTab.Logs
                                                    ),
                                                },
                                                // TODO: Add link to source code for staff
                                                {
                                                    label: 'Delete destination',
                                                    onClick: () => {
                                                        void deleteWithUndo({
                                                            endpoint: `plugin_config`, // TODO: Batch exports too
                                                            object: {
                                                                id: destination.id,
                                                                name: destination.name,
                                                            },
                                                            callback: loadPluginConfigs,
                                                        })
                                                    },
                                                    disabledReason: canConfigurePlugins
                                                        ? undefined
                                                        : 'You do not have permission to delete destinations.',
                                                },
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

function DestinationSparkLine({ destination }: { destination: Destination }): JSX.Element {
    if (destination.backend === PipelineBackend.BatchExport) {
        return <></> // TODO: not ready yet
    } else {
        const logic = pipelineNodeMetricsLogic({ pluginConfigId: destination.id })
        const { appMetricsResponse } = useValues(logic)

        const displayData: SparklineTimeSeries[] = [
            {
                color: 'success',
                name: 'Events sent',
                values: appMetricsResponse ? appMetricsResponse.metrics.successes : [],
            },
        ]
        if (appMetricsResponse?.metrics.failures.some((failure) => failure > 0)) {
            displayData.push({
                color: 'danger',
                name: 'Events dropped',
                values: appMetricsResponse ? appMetricsResponse.metrics.failures : [],
            })
        }

        return (
            <Sparkline
                loading={appMetricsResponse === null}
                labels={appMetricsResponse ? appMetricsResponse.metrics.dates : []}
                data={displayData}
            />
        )
    }
}
