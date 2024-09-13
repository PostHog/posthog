import { LemonTable, LemonTableColumn, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import { AvailableFeature, PipelineNodeTab, PipelineStage, ProductKey } from '~/types'

import { AppMetricSparkLine } from '../AppMetricSparkLine'
import { HogFunctionIcon } from '../hogfunctions/HogFunctionIcon'
import { AppMetricSparkLineV2 } from '../metrics/AppMetricsV2Sparkline'
import { NewButton } from '../NewButton'
import { pipelineAccessLogic } from '../pipelineAccessLogic'
import { Destination, PipelineBackend } from '../types'
import { pipelineNodeMenuCommonItems, RenderApp, RenderBatchExportIcon } from '../utils'
import { DestinationsFilters } from './DestinationsFilters'
import { pipelineDestinationsLogic, PipelineDestinationsLogicProps } from './destinationsLogic'
import { DestinationOptionsTable } from './NewDestinations'

export function Destinations(): JSX.Element {
    const { destinations, loading } = useValues(pipelineDestinationsLogic({ syncFiltersWithUrl: true }))

    return (
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
            <DestinationsTable syncFiltersWithUrl />
            <div className="mt-4" />
            <DestinationOptionsTable />
        </>
    )
}

export function DestinationsTable({ ...props }: PipelineDestinationsLogicProps): JSX.Element {
    const { canConfigurePlugins, canEnableDestination } = useValues(pipelineAccessLogic)
    const { loading, filteredDestinations, destinations } = useValues(pipelineDestinationsLogic(props))
    const { resetFilters, toggleNode, deleteNode } = useActions(pipelineDestinationsLogic(props))
    return (
        <div className="space-y-2">
            <DestinationsFilters />

            <BindLogic logic={pipelineDestinationsLogic} props={props}>
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
                                            PipelineStage.Destination,
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
                        {
                            title: 'Frequency',
                            key: 'interval',
                            render: function RenderFrequency(_, destination) {
                                return destination.interval
                            },
                        },
                        {
                            title: 'Weekly volume',
                            render: function RenderSuccessRate(_, destination) {
                                return (
                                    <Link
                                        to={urls.pipelineNode(
                                            PipelineStage.Destination,
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
                        },
                        updatedAtColumn() as LemonTableColumn<Destination, any>,
                        {
                            title: 'Status',
                            key: 'enabled',
                            sorter: (a) => (a.enabled ? 1 : -1),
                            width: 0,
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
                                                        onClick: () => toggleNode(destination, !destination.enabled),
                                                        disabledReason: !canConfigurePlugins
                                                            ? 'You do not have permission to toggle destinations.'
                                                            : !canEnableDestination(destination) && !destination.enabled
                                                            ? 'Data pipelines add-on is required for enabling new destinations'
                                                            : undefined,
                                                    },
                                                    ...pipelineNodeMenuCommonItems(destination),
                                                    {
                                                        label: 'Delete destination',
                                                        status: 'danger' as const, // for typechecker happiness
                                                        onClick: () => deleteNode(destination),
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
                    emptyState={
                        destinations.length === 0 && !loading ? (
                            'No destinations found'
                        ) : (
                            <>
                                No destinations matching filters.{' '}
                                <Link onClick={() => resetFilters()}>Clear filters</Link>{' '}
                            </>
                        )
                    }
                />
            </BindLogic>
        </div>
    )
}
