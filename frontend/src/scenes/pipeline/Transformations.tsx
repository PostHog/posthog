import { DndContext, DragEndEvent } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { arrayMove, SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { LemonBadge, LemonButton, LemonModal, LemonTable, LemonTableColumn, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { statusColumn, updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { urls } from 'scenes/urls'

import { PipelineNodeTab, PipelineStage, ProductKey } from '~/types'

import { AppMetricSparkLine } from './AppMetricSparkLine'
import { NewButton } from './NewButton'
import { pipelineAccessLogic } from './pipelineAccessLogic'
import { PluginImage } from './PipelinePluginImage'
import { pipelineTransformationsLogic } from './transformationsLogic'
import { Transformation } from './types'
import { appColumn, nameColumn, pipelinePluginBackedNodeMenuCommonItems } from './utils'

export function Transformations(): JSX.Element {
    const { sortedEnabledTransformations, sortedTransformations, loading } = useValues(pipelineTransformationsLogic)
    const { canConfigurePlugins } = useValues(pipelineAccessLogic)
    const { openReorderModal } = useActions(pipelineTransformationsLogic)

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
            {sortedEnabledTransformations.length > 1 && ( // Only show rearranging if there's more then 1 sortable app
                <>
                    <ReorderModal />
                    <div className="flex items-center gap-2">
                        Processed sequentially.
                        <LemonButton
                            onClick={openReorderModal}
                            noPadding
                            id="app-reorder"
                            disabledReason={
                                canConfigurePlugins ? undefined : 'You do not have permission to reorder plugins.'
                            }
                        >
                            Change order
                        </LemonButton>
                    </div>
                </>
            )}
            <TransformationsTable />
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
                        title: 'Weekly volume',
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
                ...pipelinePluginBackedNodeMenuCommonItems(
                    transformation,
                    toggleEnabled,
                    loadPluginConfigs,
                    inOverview
                ),
            ]}
        />
    )
}

function ReorderModal(): JSX.Element {
    const { reorderModalOpen, sortedEnabledTransformations, temporaryOrder, pluginConfigsLoading } =
        useValues(pipelineTransformationsLogic)
    const { closeReorderModal, setTemporaryOrder, savePluginConfigsOrder } = useActions(pipelineTransformationsLogic)

    const handleDragEnd = ({ active, over }: DragEndEvent): void => {
        if (active.id && over && active.id !== over.id) {
            // Create new sortedEnabledPluginConfigs in the order after the move
            const from = sortedEnabledTransformations.findIndex((t) => t.id === active.id)
            const to = sortedEnabledTransformations.findIndex((t) => t.id === over.id)
            const newSortedEnabledTransformations = arrayMove(sortedEnabledTransformations, from, to)
            // Create new temporaryOrder by assinging pluginConfigIds to the index in the map of newSortedEnabledPluginConfigs
            // See comment in savePluginConfigsOrder about races
            const newTemporaryOrder = newSortedEnabledTransformations.reduce((acc, pluginConfig, index) => {
                return {
                    ...acc,
                    [pluginConfig.id]: index + 1,
                }
            }, {})
            setTemporaryOrder(newTemporaryOrder)
        }
    }

    return (
        <LemonModal
            onClose={closeReorderModal}
            isOpen={reorderModalOpen}
            width={600}
            title="Reorder apps"
            description={
                <p>
                    The order of apps is important as they are processed sequentially. You can{' '}
                    <b>drag and drop the apps below</b> to change their order.
                </p>
            }
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeReorderModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        loading={pluginConfigsLoading}
                        type="primary"
                        onClick={() => savePluginConfigsOrder(temporaryOrder)}
                    >
                        Save order
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-2">
                <DndContext modifiers={[restrictToVerticalAxis, restrictToParentElement]} onDragEnd={handleDragEnd}>
                    <SortableContext items={sortedEnabledTransformations} strategy={verticalListSortingStrategy}>
                        {sortedEnabledTransformations.map((t, index) => (
                            <MinimalAppView key={t.id} transformation={t} order={index} />
                        ))}
                    </SortableContext>
                </DndContext>
            </div>
        </LemonModal>
    )
}

const MinimalAppView = ({ transformation, order }: { transformation: Transformation; order: number }): JSX.Element => {
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        id: transformation.id,
    })

    return (
        <div
            ref={setNodeRef}
            className="flex gap-2 cursor-move border rounded p-2 items-center bg-bg-light relative"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                transform: CSS.Transform.toString(transform),
                transition,
                zIndex: isDragging ? 999999 : undefined,
            }}
            {...attributes}
            {...listeners}
        >
            <LemonBadge.Number count={order + 1} maxDigits={3} />
            <PluginImage plugin={transformation.plugin} size="small" />
            <span className="font-semibold">{transformation.name}</span>
        </div>
    )
}
