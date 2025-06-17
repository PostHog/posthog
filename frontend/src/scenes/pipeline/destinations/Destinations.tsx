import { DndContext, DragEndEvent } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { arrayMove, SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { LemonTable, LemonTableColumn, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'
import { LemonBadge, LemonButton, LemonModal } from '@posthog/lemon-ui'
import { clsx } from 'clsx'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { useEffect, useState } from 'react'
import { RenderBatchExportIcon } from 'scenes/data-pipelines/batch-exports/BatchExportIcon'
import { HogFunctionMetricSparkLine } from 'scenes/hog-functions/metrics/HogFunctionMetricsSparkline'
import { urls } from 'scenes/urls'

import { AvailableFeature, HogFunctionTypeType, PipelineNodeTab, PipelineStage, ProductKey } from '~/types'

import { HogFunctionIcon } from '../../hog-functions/configuration/HogFunctionIcon'
import { HogFunctionStatusIndicator } from '../../hog-functions/misc/HogFunctionStatusIndicator'
import { hogFunctionTypeToPipelineStage } from '../../hog-functions/misc/urls'
import { AppMetricSparkLine } from '../AppMetricSparkLine'
import { FrontendApps } from '../FrontendApps'
import { NewButton } from '../NewButton'
import { pipelineAccessLogic } from '../pipelineAccessLogic'
import { Destination, FunctionDestination, PipelineBackend, SiteApp, Transformation } from '../types'
import { pipelineNodeMenuCommonItems, RenderApp } from '../utils'
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
            ) : types.includes('transformation') ? (
                <>
                    <ReorderTransformationsModal types={types} />
                </>
            ) : null}

            <DestinationsTable types={types} />
            <div className="mt-4" />
            <h2>
                {types.includes('destination')
                    ? 'New destinations'
                    : types.includes('site_app')
                    ? 'New site app'
                    : types.includes('transformation')
                    ? 'New transformation'
                    : 'New'}
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
    hideChangeOrderButton?: boolean
}

export function DestinationsTable({
    hideFeedback,
    hideAddDestinationButton,
    types,
    hideChangeOrderButton = false,
}: DestinationsTableProps): JSX.Element {
    const { canConfigurePlugins, canEnableDestination } = useValues(pipelineAccessLogic)
    const { loading, filteredDestinations, destinations, hiddenDestinations } = useValues(
        pipelineDestinationsLogic({ types })
    )
    const { toggleNode, deleteNode, openReorderTransformationsModal } = useActions(pipelineDestinationsLogic({ types }))
    const { resetFilters } = useActions(destinationsFiltersLogic({ types }))

    const showMetricsHistory = types.includes('destination') || types.includes('transformation')
    const showFrequencyInterval = types.includes('destination')
    const simpleName =
        types.includes('destination') || types.includes('site_destination')
            ? 'destination'
            : types.includes('site_app')
            ? 'site app'
            : 'Hog function'

    const enabledTransformations = destinations.filter(
        (d): d is FunctionDestination => d.stage === PipelineStage.Transformation && d.enabled
    )

    const showPriorityColumn = types.includes('transformation')

    return (
        <div className="deprecated-space-y-4">
            <DestinationsFilters
                types={types}
                hideFeedback={hideFeedback}
                hideAddDestinationButton={hideAddDestinationButton}
            />

            {types.includes('transformation') && enabledTransformations.length > 1 && !hideChangeOrderButton && (
                <div className="flex gap-2 items-center">
                    Processed sequentially.
                    <LemonButton
                        onClick={() => openReorderTransformationsModal()}
                        noPadding
                        id="transformation-reorder"
                        disabledReason={
                            canConfigurePlugins ? undefined : 'You do not have permission to reorder Transformations.'
                        }
                    >
                        Change order
                    </LemonButton>
                </div>
            )}

            <LemonTable
                dataSource={filteredDestinations}
                size="small"
                loading={loading}
                columns={[
                    ...(showPriorityColumn
                        ? [
                              {
                                  title: 'Prio',
                                  key: 'order',
                                  width: 0,
                                  align: 'center',
                                  sorter: (a, b) => {
                                      if (
                                          a.backend === PipelineBackend.HogFunction &&
                                          b.backend === PipelineBackend.HogFunction
                                      ) {
                                          const orderA = a.hog_function.execution_order || 0
                                          const orderB = b.hog_function.execution_order || 0
                                          return orderA - orderB
                                      }
                                      return 0
                                  },
                                  render: function RenderOrdering(_, destination) {
                                      if (destination.backend === PipelineBackend.HogFunction && destination.enabled) {
                                          const enabledTransformations = filteredDestinations
                                              .filter(
                                                  (d): d is FunctionDestination =>
                                                      d.backend === PipelineBackend.HogFunction && d.enabled
                                              )
                                              .sort(
                                                  (a, b) =>
                                                      (a.hog_function.execution_order || 0) -
                                                      (b.hog_function.execution_order || 0)
                                              )

                                          const index = enabledTransformations.findIndex((t) => t.id === destination.id)
                                          return <div className="text-center">{index + 1}</div>
                                      }
                                      return null
                                  },
                              } as LemonTableColumn<Destination | Transformation | SiteApp, any>,
                          ]
                        : []),
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
                        key: 'name',
                        dataIndex: 'name',
                        sorter: (a, b) => (a.name || '').localeCompare(b.name || ''),
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
                    ...(showFrequencyInterval
                        ? [
                              {
                                  title: 'Frequency',
                                  key: 'interval',
                                  render: function RenderFrequency(_, destination) {
                                      return 'interval' in destination ? destination.interval : null
                                  },
                              } as LemonTableColumn<Destination | Transformation | SiteApp, any>,
                          ]
                        : []),
                    ...(showMetricsHistory
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
                                                  <HogFunctionMetricSparkLine id={destination.hog_function.id} />
                                              ) : (
                                                  <AppMetricSparkLine pipelineNode={destination} />
                                              )}
                                          </Link>
                                      )
                                  },
                              } as LemonTableColumn<Destination | Transformation | SiteApp, any>,
                          ]
                        : []),
                    updatedAtColumn() as LemonTableColumn<Destination | Transformation | SiteApp, any>,
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
                <div className="text-secondary">
                    {hiddenDestinations.length} hidden. <Link onClick={() => resetFilters()}>Show all</Link>
                </div>
            )}
        </div>
    )
}

function ReorderTransformationsModal({ types }: { types: HogFunctionTypeType[] }): JSX.Element {
    const { reorderTransformationsModalOpen, destinations, temporaryTransformationOrder, loading } = useValues(
        pipelineDestinationsLogic({ types })
    )
    const { closeReorderTransformationsModal, setTemporaryTransformationOrder, saveTransformationsOrder } = useActions(
        pipelineDestinationsLogic({ types })
    )
    const [initialOrders, setInitialOrders] = useState<Record<string, number>>({})

    const enabledTransformations = destinations.filter(
        (d): d is FunctionDestination => d.stage === PipelineStage.Transformation && d.enabled
    )

    // Store initial orders when modal opens
    useEffect(() => {
        if (reorderTransformationsModalOpen) {
            const orders = enabledTransformations.reduce(
                (acc, transformation) => ({
                    ...acc,
                    [transformation.hog_function.id]: transformation.hog_function.execution_order || 0,
                }),
                {} as Record<string, number>
            )
            setInitialOrders(orders)
        }
    }, [reorderTransformationsModalOpen, enabledTransformations])

    // Sort transformations based on temporaryOrder if it exists
    const sortedTransformations = [...enabledTransformations]
    if (Object.keys(temporaryTransformationOrder).length > 0) {
        sortedTransformations.sort((a, b) => {
            // Use hog_function.id for sorting
            const orderA = temporaryTransformationOrder[a.hog_function.id] || 0
            const orderB = temporaryTransformationOrder[b.hog_function.id] || 0
            return orderA - orderB
        })
    }

    const handleDragEnd = ({ active, over }: DragEndEvent): void => {
        if (active.id && over && active.id !== over.id) {
            const from = sortedTransformations.findIndex((d) => d.id === active.id)
            const to = sortedTransformations.findIndex((d) => d.id === over.id)
            const newSortedDestinations = arrayMove(sortedTransformations, from, to)

            const newTemporaryOrder = newSortedDestinations.reduce((acc, destination, index) => {
                if (destination.hog_function?.id) {
                    return {
                        ...acc,
                        [destination.hog_function.id]: index + 1,
                    }
                }
                return acc
            }, {} as Record<string, number>)

            setTemporaryTransformationOrder(newTemporaryOrder)
        }
    }

    const handleSaveOrder = (): void => {
        // Compare and only include changed orders
        const changedOrders = Object.entries(temporaryTransformationOrder).reduce((acc, [id, newOrder]) => {
            const originalOrder = initialOrders[id]
            if (originalOrder !== newOrder) {
                return {
                    ...acc,
                    [id]: newOrder,
                }
            }
            return acc
        }, {} as Record<string, number>)

        // Only send if there are changes
        if (Object.keys(changedOrders).length > 0) {
            saveTransformationsOrder(changedOrders)
        } else {
            closeReorderTransformationsModal()
        }
    }

    return (
        <LemonModal
            onClose={closeReorderTransformationsModal}
            isOpen={reorderTransformationsModalOpen}
            width={600}
            title="Reorder transformations"
            description={
                <p>
                    The order of transformations is important as they are processed sequentially. You can{' '}
                    <b>drag and drop the transformations below</b> to change their order.
                </p>
            }
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeReorderTransformationsModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton loading={loading} type="primary" onClick={handleSaveOrder}>
                        Save order
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-2">
                <DndContext modifiers={[restrictToVerticalAxis, restrictToParentElement]} onDragEnd={handleDragEnd}>
                    <SortableContext items={sortedTransformations} strategy={verticalListSortingStrategy}>
                        {sortedTransformations.map((transformation, index) => (
                            <MinimalTransformationView
                                key={transformation.id}
                                transformation={transformation}
                                order={index}
                            />
                        ))}
                    </SortableContext>
                </DndContext>
            </div>
        </LemonModal>
    )
}

const MinimalTransformationView = ({
    transformation,
    order,
}: {
    transformation: FunctionDestination
    order: number
}): JSX.Element => {
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        id: transformation.id,
    })

    return (
        <div
            ref={setNodeRef}
            className={clsx(
                'relative flex items-center gap-2 p-2 border rounded cursor-move bg-bg-light',
                isDragging && 'z-[999999]'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                transform: CSS.Transform.toString(transform),
                transition,
            }}
            {...attributes}
            {...listeners}
        >
            <LemonBadge.Number count={order + 1} maxDigits={3} />
            <span className="font-semibold">{transformation.name}</span>
        </div>
    )
}
