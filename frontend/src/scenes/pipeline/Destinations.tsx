import { LemonButton, LemonDivider, LemonTable, LemonTableColumn, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { FEATURE_FLAGS } from 'lib/constants'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown/LemonMarkdown'
import { updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'

import { PipelineAppKind, ProductKey } from '~/types'

import { AppMetricSparkLine } from './AppMetricSparkLine'
import { DestinationType, pipelineDestinationsLogic } from './destinationsLogic'
import { NewButton } from './NewButton'
import { RenderApp, RenderBatchExportIcon } from './utils'

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
                    actionElementOverride={<NewButton kind={PipelineAppKind.Destination} />}
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
                                        <Link to={destination.config_url}>
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
                            return <RenderBatchExportIcon type={destination.data_storage_type} />
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
                            return <AppMetricSparkLine config={destination} />
                        },
                    },
                    updatedAtColumn() as LemonTableColumn<DestinationType, any>,
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
    destination: DestinationType
    inOverview?: boolean
}): JSX.Element => {
    const { canConfigurePlugins } = useValues(pipelineDestinationsLogic)
    const { toggleEnabled, loadPluginConfigs } = useActions(pipelineDestinationsLogic)

    return (
        <>
            {!inOverview && (
                <LemonButton
                    onClick={() => toggleEnabled(destination, !destination.enabled)}
                    id={`app-${destination.id}-enable-switch`}
                    disabledReason={
                        canConfigurePlugins ? undefined : 'You do not have permission to enable/disable destinations.'
                    }
                    fullWidth
                >
                    {destination.enabled ? 'Pause' : 'Unpause'} destination
                </LemonButton>
            )}
            <LemonButton to={destination.config_url} id={`app-${destination.id}-configuration`} fullWidth>
                {canConfigurePlugins ? 'Edit' : 'View'} destination configuration
            </LemonButton>
            <LemonButton to={destination.metrics_url} id={`app-${destination.id}-metrics`} fullWidth>
                View metrics
            </LemonButton>
            <LemonButton to={destination.logs_url} id={`app-${destination.id}-logs`} fullWidth>
                View logs
            </LemonButton>
            {destination.app_source_code_url && (
                <LemonButton
                    to={destination.app_source_code_url}
                    targetBlank={true}
                    id={`app-${destination.id}-source-code`}
                    fullWidth
                >
                    View app source code
                </LemonButton>
            )}

            {!inOverview && destination.backend === 'plugin' && (
                <>
                    <LemonDivider />
                    <LemonButton // TODO: batch exports
                        status="danger"
                        onClick={() => {
                            void deleteWithUndo({
                                endpoint: `plugin_config`,
                                object: {
                                    id: destination.id,
                                    name: destination.name,
                                },
                                callback: loadPluginConfigs,
                            })
                        }}
                        id="app-delete"
                        disabledReason={canConfigurePlugins ? undefined : 'You do not have permission to delete apps.'}
                        fullWidth
                    >
                        Delete app
                    </LemonButton>
                </>
            )}
        </>
    )
}
