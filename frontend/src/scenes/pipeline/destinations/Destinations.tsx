import { LemonTable, LemonTableColumn, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import { AvailableFeature, HogFunctionTypeType, PipelineNodeTab, PipelineStage, ProductKey } from '~/types'

import { AppMetricSparkLine } from '../AppMetricSparkLine'
import { FrontendApps } from '../FrontendApps'
import { HogFunctionIcon } from '../hogfunctions/HogFunctionIcon'
import { HogFunctionStatusIndicator } from '../hogfunctions/HogFunctionStatusIndicator'
import { hogFunctionTypeToPipelineStage } from '../hogfunctions/urls'
import { AppMetricSparkLineV2 } from '../metrics/AppMetricsV2Sparkline'
import { NewButton } from '../NewButton'
import { pipelineAccessLogic } from '../pipelineAccessLogic'
import { Destination, PipelineBackend, SiteApp } from '../types'
import { pipelineNodeMenuCommonItems, RenderApp, RenderBatchExportIcon } from '../utils'
import { DestinationsFilters } from './DestinationsFilters'
import { destinationsFiltersLogic } from './destinationsFiltersLogic'
import { pipelineDestinationsLogic } from './destinationsLogic'
import { DestinationOptionsTable } from './NewDestinations'

export interface DestinationsProps {
    types: HogFunctionTypeType[]
}

export function Destinations({ types }: DestinationsProps): JSX.Element {
    const { destinations, loading } = useValues(pipelineDestinationsLogic({ types }))

    return (
        <>
            {types.includes('destination') ? (
                <>
                    <PageHeader
                        caption="Send your data in real time or in batches to destinations outside of PostHog."
                        buttons={<NewButton stage={PipelineStage.Destination} />}
                    />
                    <PayGateMini feature={AvailableFeature.DATA_PIPELINES} className="mb-2">
                        <ProductIntroduction
                            productName="Pipeline destinations"
                            thingName="destination"
                            productKey={ProductKey.PIPELINE_DESTINATIONS}
                            description="Pipeline destinations allow you to export data outside of PostHog, such as webhooks to Slack."
                            docsURL="https://posthog.com/docs/cdp"
                            actionElementOverride={<NewButton stage={PipelineStage.Destination} />}
                            isEmpty={destinations.length === 0 && !loading}
                        />
                    </PayGateMini>
                </>
            ) : types.includes('site_app') ? (
                <PageHeader
                    caption="Run custom scripts on your website."
                    buttons={<NewButton stage={PipelineStage.SiteApp} />}
                />
            ) : (
                <PageHeader
                    caption="Run custom scripts on your website or send your data in real time or in batches to destinations outside of PostHog."
                    buttons={<NewButton stage={PipelineStage.SiteApp} />}
                />
            )}

            <DestinationsTable types={types} />
            <div className="mt-4" />
            <h2>
                {types.includes('destination')
                    ? 'New destinations'
                    : types.includes('site_app')
                    ? 'New site app'
                    : 'New Hog function'}
            </h2>
            <DestinationOptionsTable types={types} />
            {/* Old site-apps until we migrate everyone onto the new ones */}
            {types.includes('site_app') ? <FrontendApps asLegacyList /> : null}
        </>
    )
}
export type DestinationsTableProps = {
    types: HogFunctionTypeType[]
    hideFeedback?: boolean
    hideAddDestinationButton?: boolean
}

export function DestinationsTable({
    hideFeedback,
    hideAddDestinationButton,
    types,
}: DestinationsTableProps): JSX.Element {
    const { canConfigurePlugins, canEnableDestination } = useValues(pipelineAccessLogic)
    const { loading, filteredDestinations, destinations, hiddenDestinations } = useValues(
        pipelineDestinationsLogic({ types })
    )
    const { toggleNode, deleteNode } = useActions(pipelineDestinationsLogic({ types }))
    const { resetFilters } = useActions(destinationsFiltersLogic({ types }))

    const showFrequencyHistory = types.includes('destination')
    const simpleName =
        types.includes('destination') || types.includes('site_destination')
            ? 'destination'
            : types.includes('site_app')
            ? 'site app'
            : 'Hog function'

    return (
        <div className="space-y-2">
            <DestinationsFilters
                types={types}
                hideFeedback={hideFeedback}
                hideAddDestinationButton={hideAddDestinationButton}
            />

            <LemonTable
                dataSource={filteredDestinations}
                size="small"
                loading={loading}
                columns={[
                    {
                        title: 'App',
                        width: 0,
                        render: function RenderAppInfo(_, destination) {
                            switch (destination.backend) {
                                case 'plugin':
                                    return <RenderApp plugin={destination.plugin} />
                                case 'hog_function':
                                    return <HogFunctionIcon src={destination.hog_function.icon_url} size="small" />
                                case 'batch_export':
                                    return <RenderBatchExportIcon type={destination.service.type} />
                                default:
                                    return null
                            }
                        },
                    },
                    {
                        title: 'Name',
                        sticky: true,
                        sorter: true,
                        key: 'name',
                        dataIndex: 'name',
                        render: function RenderPluginName(_, destination) {
                            return (
                                <LemonTableLink
                                    to={urls.pipelineNode(
                                        hogFunctionTypeToPipelineStage(destination.stage),
                                        destination.id,
                                        PipelineNodeTab.Configuration
                                    )}
                                    title={
                                        <>
                                            <Tooltip title="Click to update configuration, view metrics, and more">
                                                <span>{destination.name}</span>
                                            </Tooltip>
                                        </>
                                    }
                                    description={destination.description}
                                />
                            )
                        },
                    },
                    ...(showFrequencyHistory
                        ? [
                              {
                                  title: 'Frequency',
                                  key: 'interval',
                                  render: function RenderFrequency(_, destination) {
                                      return 'interval' in destination ? destination.interval : null
                                  },
                              } as LemonTableColumn<Destination | SiteApp, any>,
                          ]
                        : []),
                    ...(showFrequencyHistory
                        ? [
                              {
                                  title: 'Last 7 days',
                                  render: function RenderSuccessRate(_, destination) {
                                      return (
                                          <Link
                                              to={urls.pipelineNode(
                                                  hogFunctionTypeToPipelineStage(destination.stage),
                                                  destination.id,
                                                  PipelineNodeTab.Metrics
                                              )}
                                          >
                                              {destination.backend === PipelineBackend.HogFunction ? (
                                                  <AppMetricSparkLineV2 id={destination.hog_function.id} />
                                              ) : (
                                                  <AppMetricSparkLine pipelineNode={destination} />
                                              )}
                                          </Link>
                                      )
                                  },
                              } as LemonTableColumn<Destination | SiteApp, any>,
                          ]
                        : []),
                    updatedAtColumn() as LemonTableColumn<Destination | SiteApp, any>,
                    {
                        title: 'Status',
                        key: 'enabled',
                        sorter: (a) => (a.enabled ? 1 : -1),
                        width: 0,
                        render: function RenderStatus(_, destination) {
                            if (destination.backend === PipelineBackend.HogFunction) {
                                return <HogFunctionStatusIndicator hogFunction={destination.hog_function} />
                            }
                            return (
                                <>
                                    {destination.enabled ? (
                                        <LemonTag type="success">Active</LemonTag>
                                    ) : (
                                        <LemonTag type="default">Disabled</LemonTag>
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
                                                        ? `Pause ${simpleName}`
                                                        : `Unpause ${simpleName}`,
                                                    onClick: () => toggleNode(destination, !destination.enabled),
                                                    disabledReason: !canConfigurePlugins
                                                        ? `You do not have permission to toggle ${simpleName}s.`
                                                        : !canEnableDestination(destination) && !destination.enabled
                                                        ? `Data pipelines add-on is required for enabling new ${simpleName}s`
                                                        : undefined,
                                                },
                                                ...pipelineNodeMenuCommonItems(destination),
                                                {
                                                    label: `Delete ${simpleName}`,
                                                    status: 'danger' as const, // for typechecker happiness
                                                    onClick: () => deleteNode(destination),
                                                    disabledReason: canConfigurePlugins
                                                        ? undefined
                                                        : `You do not have permission to delete ${simpleName}.`,
                                                },
                                            ]}
                                        />
                                    }
                                />
                            )
                        },
                    },
                ]}
                emptyState={
                    destinations.length === 0 && !loading ? (
                        'No destinations found'
                    ) : (
                        <>
                            No destinations matching filters. <Link onClick={() => resetFilters()}>Clear filters</Link>{' '}
                        </>
                    )
                }
            />

            {hiddenDestinations.length > 0 && (
                <div className="text-muted-alt">
                    {hiddenDestinations.length} hidden. <Link onClick={() => resetFilters()}>Show all</Link>
                </div>
            )}
        </div>
    )
}
