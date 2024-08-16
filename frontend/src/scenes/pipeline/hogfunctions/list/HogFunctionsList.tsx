import { LemonCheckbox, LemonInput, LemonTable, LemonTableColumn, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { AppMetricSparkLineV2 } from 'scenes/pipeline/metrics/AppMetricsV2Sparkline'
import { urls } from 'scenes/urls'

import { AvailableFeature, PipelineNodeTab, PipelineStage, ProductKey } from '~/types'

import { HogFunctionIcon } from '../hogfunctions/HogFunctionIcon'
import { NewButton } from '../NewButton'
import { pipelineAccessLogic } from '../pipelineAccessLogic'
import { Destination } from '../types'
import { pipelineNodeMenuCommonItems } from '../utils'
import { hogFunctionsListLogic, HogFunctionsListLogicProps } from './hogFunctionsListLogic'

export function HogFunctionsListScene(): JSX.Element {
    const { hogFunctions, loading } = useValues(hogFunctionsListLogic({ syncFiltersWithUrl: true }))

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
                    isEmpty={hogFunctions.length === 0 && !loading}
                />
            </PayGateMini>
            <HogFunctionsList syncFiltersWithUrl />
        </>
    )
}

export function HogFunctionsList({
    extraControls,
    ...props
}: HogFunctionsListLogicProps & { extraControls?: JSX.Element }): JSX.Element {
    const { loading, filteredHogFunctions, filters, hogFunctions } = useValues(hogFunctionsListLogic(props))
    const { setFilters, resetFilters } = useActions(hogFunctionsListLogic(props))

    return (
        <>
            <div className="flex items-center mb-2 gap-2">
                {!props.forceFilters?.search && (
                    <LemonInput
                        type="search"
                        placeholder="Search..."
                        value={filters.search ?? ''}
                        onChange={(e) => setFilters({ search: e })}
                    />
                )}
                <div className="flex-1" />
                {typeof props.forceFilters?.onlyActive !== 'boolean' && (
                    <LemonCheckbox
                        label="Only active"
                        bordered
                        size="small"
                        checked={filters.onlyActive}
                        onChange={(e) => setFilters({ onlyActive: e ?? undefined })}
                    />
                )}
                {extraControls}
            </div>

            <BindLogic logic={hogFunctionsListLogic} props={props}>
                <LemonTable
                    dataSource={filteredHogFunctions}
                    size="small"
                    loading={loading}
                    columns={[
                        {
                            title: '',
                            width: 0,
                            render: function RenderIcon(_, hogFunction) {
                                return <HogFunctionIcon src={hogFunction.icon_url} size="small" />
                            },
                        },
                        {
                            title: 'Name',
                            sticky: true,
                            sorter: true,
                            key: 'name',
                            dataIndex: 'name',
                            render: (_, hogFunction) => {
                                return (
                                    <LemonTableLink
                                        to={urls.pipelineNode(
                                            PipelineStage.Destination,
                                            `hog-${hogFunction.id}`,
                                            PipelineNodeTab.Configuration
                                        )}
                                        title={
                                            <>
                                                <Tooltip title="Click to update configuration, view metrics, and more">
                                                    <span>{hogFunction.name}</span>
                                                </Tooltip>
                                            </>
                                        }
                                        description={hogFunction.description}
                                    />
                                )
                            },
                        },
                        {
                            title: 'Frequency',
                            key: 'interval',
                            render: (_, hogFunction) => {
                                return hogFunction.interval
                            },
                        },
                        {
                            title: 'Weekly volume',
                            render: (_, hogFunction) => {
                                return (
                                    <Link
                                        to={urls.pipelineNode(
                                            PipelineStage.Destination,
                                            `hog-${hogFunction.id}`,
                                            PipelineNodeTab.Metrics
                                        )}
                                    >
                                        <AppMetricSparkLineV2 id={hogFunction.id} />
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
                                return <More overlay={<DestinationMoreOverlay destination={destination} />} />
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
        </>
    )
}

const DestinationMoreOverlay = ({ destination }: { destination: Destination }): JSX.Element => {
    const { canConfigurePlugins, canEnableDestination } = useValues(pipelineAccessLogic)
    const { toggleNode, deleteNode } = useActions(pipelineDestinationsLogic)

    return (
        <LemonMenuOverlay
            items={[
                {
                    label: destination.enabled ? 'Pause destination' : 'Unpause destination',
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
    )
}
