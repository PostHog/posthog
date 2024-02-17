import { LemonTable, LemonTableColumn, LemonTag, lemonToast, Link, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { FEATURE_FLAGS } from 'lib/constants'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown/LemonMarkdown'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { urls } from 'scenes/urls'

import { PipelineNodeTab, PipelineStage, ProductKey } from '~/types'

import { AppMetricSparkLine } from './AppMetricSparkLine'
import { pipelineDestinationsLogic } from './destinationsLogic'
import { NewButton } from './NewButton'
import { Destination, PipelineBackend } from './types'
import { RenderApp, RenderBatchExportIcon } from './utils'

export function Destinations(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.PIPELINE_UI]) {
        return <p>Pipeline 3000 not available yet</p>
    }
    const { destinations, shouldShowProductIntroduction } = useValues(pipelineDestinationsLogic)

    const shouldShowEmptyState = !destinations.some((destination) => destination.enabled)

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
    const { loading, destinations } = useValues(pipelineDestinationsLogic)

    return (
        <>
            <LemonTable
                dataSource={destinations}
                size="small"
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
                                            to={urls.pipelineNode(
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
                            return <RenderBatchExportIcon type={destination.service.type} />
                        },
                    },
                    {
                        title: 'Frequency',
                        render: function RenderFrequency(_, destination) {
                            return destination.interval
                        },
                    },
                    {
                        title: 'Success rate',
                        render: function RenderSuccessRate(_, destination) {
                            return <AppMetricSparkLine pipelineNode={destination} />
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
                            return <More overlay={<DestinationMoreOverlay destination={destination} />} />
                        },
                    },
                ]}
            />
        </>
    )
}

export const DestinationMoreOverlay = ({
    destination,
    inOverview = false,
}: {
    destination: Destination
    inOverview?: boolean
}): JSX.Element => {
    const { canConfigurePlugins } = useValues(pipelineDestinationsLogic)
    const { toggleEnabled, loadPluginConfigs } = useActions(pipelineDestinationsLogic)

    return (
        <LemonMenuOverlay
            items={[
                ...(!inOverview
                    ? [
                          {
                              label: destination.enabled ? 'Pause destination' : 'Unpause destination',
                              onClick: () => toggleEnabled(destination, !destination.enabled),
                              disabledReason: canConfigurePlugins
                                  ? undefined
                                  : 'You do not have permission to enable/disable destinations.',
                          },
                      ]
                    : []),
                {
                    label: canConfigurePlugins ? 'Edit configuration' : 'View configuration',
                    to: urls.pipelineNode(PipelineStage.Destination, destination.id, PipelineNodeTab.Configuration),
                },
                {
                    label: 'View metrics',
                    to: urls.pipelineNode(PipelineStage.Destination, destination.id, PipelineNodeTab.Metrics),
                },
                {
                    label: 'View logs',
                    to: urls.pipelineNode(PipelineStage.Destination, destination.id, PipelineNodeTab.Logs),
                },
                // TODO: Add link to source code for staff
                {
                    label: 'Delete destination',
                    onClick: () => {
                        if (destination.backend === PipelineBackend.Plugin) {
                            void deleteWithUndo({
                                endpoint: `plugin_config`, // TODO: Batch exports too
                                object: {
                                    id: destination.id,
                                    name: destination.name,
                                },
                                callback: loadPluginConfigs,
                            })
                        } else {
                            lemonToast.warning('Deleting batch export destinations is not yet supported here.')
                        }
                    },
                    disabledReason: canConfigurePlugins
                        ? undefined
                        : 'You do not have permission to delete destinations.',
                },
            ]}
        />
    )
}
