import {
    LemonButton,
    LemonDivider,
    LemonTable,
    LemonTableColumn,
    LemonTag,
    LemonTagType,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { FEATURE_FLAGS } from 'lib/constants'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown/LemonMarkdown'
import { updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { urls } from 'scenes/urls'

import { PipelineAppTabs, PipelineTabs, PluginConfigTypeNew, ProductKey } from '~/types'

import { pipelineDestinationsLogic } from './destinationsLogic'
import { NewButton } from './NewButton'
import { RenderApp } from './utils'

export function Destinations(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.PIPELINE_UI]) {
        return <></>
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
                    actionElementOverride={<NewButton tab={PipelineTabs.Destinations} />}
                    isEmpty={true}
                />
            )}
            <AppsTable />
            <BatchExportsTable />
        </>
    )
}

function BatchExportsTable(): JSX.Element {
    return (
        <>
            <h2>Batch exports</h2>

            <h2>Backfills</h2>
        </>
    )
}

function AppsTable(): JSX.Element {
    const { loading, enabledPluginConfigs, disabledPluginConfigs, plugins, canConfigurePlugins } =
        useValues(pipelineDestinationsLogic)
    const { toggleEnabled, loadPluginConfigs } = useActions(pipelineDestinationsLogic)

    if (enabledPluginConfigs.length === 0 && disabledPluginConfigs.length === 0) {
        return <></>
    }

    return (
        <>
            <h2>Webhooks</h2>
            <LemonTable
                dataSource={[...enabledPluginConfigs, ...disabledPluginConfigs]}
                size="xs"
                loading={loading}
                columns={[
                    {
                        title: 'Name',
                        sticky: true,
                        render: function RenderPluginName(_, pluginConfig) {
                            return (
                                <>
                                    <Tooltip title={'Click to update configuration, view metrics, and more'}>
                                        <Link to={urls.pipelineApp(pluginConfig.id, PipelineAppTabs.Configuration)}>
                                            <span className="row-name">{pluginConfig.name}</span>
                                        </Link>
                                    </Tooltip>
                                    {pluginConfig.description && (
                                        <LemonMarkdown className="row-description" lowKeyHeadings>
                                            {pluginConfig.description}
                                        </LemonMarkdown>
                                    )}
                                </>
                            )
                        },
                    },
                    {
                        title: 'App',
                        render: function RenderAppInfo(_, pluginConfig) {
                            return <RenderApp plugin={plugins[pluginConfig.plugin]} />
                        },
                    },
                    {
                        title: '24h',
                        render: function Render24hDeliveryRate(_, pluginConfig) {
                            let tooltip = 'No events exported in the past 24 hours'
                            let value = '-'
                            let tagType: LemonTagType = 'muted'
                            if (
                                pluginConfig.delivery_rate_24h !== null &&
                                pluginConfig.delivery_rate_24h !== undefined
                            ) {
                                const deliveryRate = pluginConfig.delivery_rate_24h
                                value = `${Math.floor(deliveryRate * 100)}%`
                                tooltip = 'Success rate for past 24 hours'
                                if (deliveryRate >= 0.99) {
                                    tagType = 'success'
                                } else if (deliveryRate >= 0.75) {
                                    tagType = 'warning'
                                } else {
                                    tagType = 'danger'
                                }
                            }
                            return (
                                <Tooltip title={tooltip}>
                                    <Link to={urls.pipelineApp(pluginConfig.id, PipelineAppTabs.Metrics)}>
                                        <LemonTag type={tagType}>{value}</LemonTag>
                                    </Link>
                                </Tooltip>
                            )
                        },
                    },
                    updatedAtColumn() as LemonTableColumn<PluginConfigTypeNew, any>,
                    {
                        title: 'Status',
                        render: function RenderStatus(_, pluginConfig) {
                            return (
                                <>
                                    {pluginConfig.enabled ? (
                                        <LemonTag type="success" className="uppercase">
                                            Enabled
                                        </LemonTag>
                                    ) : (
                                        <LemonTag type="default" className="uppercase">
                                            Disabled
                                        </LemonTag>
                                    )}
                                </>
                            )
                        },
                    },
                    {
                        width: 0,
                        render: function Render(_, pluginConfig) {
                            return (
                                <More
                                    overlay={
                                        <>
                                            <LemonButton
                                                onClick={() => {
                                                    toggleEnabled({
                                                        enabled: !pluginConfig.enabled,
                                                        id: pluginConfig.id,
                                                    })
                                                }}
                                                id={`app-${pluginConfig.id}-enable-switch`}
                                                disabledReason={
                                                    canConfigurePlugins
                                                        ? undefined
                                                        : 'You do not have permission to enable/disable apps.'
                                                }
                                                fullWidth
                                            >
                                                {pluginConfig.enabled ? 'Disable' : 'Enable'} app
                                            </LemonButton>
                                            <LemonButton
                                                to={urls.pipelineApp(pluginConfig.id, PipelineAppTabs.Configuration)}
                                                id={`app-${pluginConfig.id}-configuration`}
                                                fullWidth
                                            >
                                                {canConfigurePlugins ? 'Edit' : 'View'} app configuration
                                            </LemonButton>
                                            <LemonButton
                                                to={urls.pipelineApp(pluginConfig.id, PipelineAppTabs.Metrics)}
                                                id={`app-${pluginConfig.id}-metrics`}
                                                fullWidth
                                            >
                                                View app metrics
                                            </LemonButton>
                                            <LemonButton
                                                to={urls.pipelineApp(pluginConfig.id, PipelineAppTabs.Logs)}
                                                id={`app-${pluginConfig.id}-logs`}
                                                fullWidth
                                            >
                                                View app logs
                                            </LemonButton>
                                            {plugins[pluginConfig.plugin].url && (
                                                <LemonButton
                                                    to={plugins[pluginConfig.plugin].url}
                                                    targetBlank={true}
                                                    id={`app-${pluginConfig.id}-source-code`}
                                                    fullWidth
                                                >
                                                    View app source code
                                                </LemonButton>
                                            )}
                                            <LemonDivider />
                                            <LemonButton
                                                status="danger"
                                                onClick={() => {
                                                    void deleteWithUndo({
                                                        endpoint: `plugin_config`,
                                                        object: {
                                                            id: pluginConfig.id,
                                                            name: pluginConfig.name,
                                                        },
                                                        callback: loadPluginConfigs,
                                                    })
                                                }}
                                                id="app-reorder"
                                                disabledReason={
                                                    canConfigurePlugins
                                                        ? undefined
                                                        : 'You do not have permission to delete apps.'
                                                }
                                                fullWidth
                                            >
                                                Delete app
                                            </LemonButton>
                                        </>
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
