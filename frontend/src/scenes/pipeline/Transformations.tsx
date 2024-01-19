import { DndContext, DragEndEvent } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { arrayMove, SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import {
    LemonBadge,
    LemonButton,
    LemonDivider,
    LemonModal,
    LemonTable,
    LemonTableColumn,
    LemonTag,
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
import { PluginImage } from 'scenes/plugins/plugin/PluginImage'
import { urls } from 'scenes/urls'

import {
    PipelineAppKind,
    PipelineAppTab,
    PluginConfigTypeNew,
    PluginConfigWithPluginInfoNew,
    ProductKey,
} from '~/types'

import { NewButton } from './NewButton'
import { pipelineTransformationsLogic } from './transformationsLogic'
import { RenderApp } from './utils'

export function Transformations(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.PIPELINE_UI]) {
        return <p>Pipeline 3000 not available yet</p>
    }
    const {
        loading,
        sortedEnabledPluginConfigs,
        disabledPluginConfigs,
        displayablePluginConfigs,
        canConfigurePlugins,
        shouldShowProductIntroduction,
    } = useValues(pipelineTransformationsLogic)
    const { openReorderModal } = useActions(pipelineTransformationsLogic)

    const shouldShowEmptyState = sortedEnabledPluginConfigs.length === 0 && disabledPluginConfigs.length === 0

    return (
        <>
            {(shouldShowEmptyState || shouldShowProductIntroduction) && (
                <ProductIntroduction
                    productName="Pipeline transformations"
                    thingName="transformation"
                    productKey={ProductKey.PIPELINE_TRANSFORMATIONS}
                    description="Pipeline transformations allow you to enrich your data with additional information, such as geolocation."
                    docsURL="https://posthog.com/docs/cdp"
                    actionElementOverride={<NewButton kind={PipelineAppKind.Transformation} />}
                    isEmpty={true}
                />
            )}
            {!shouldShowEmptyState && (
                <>
                    {sortedEnabledPluginConfigs.length > 1 && ( // Only show rearranging if there's more then 1 sortable app
                        <>
                            <ReorderModal />
                            <div className="flex items-center gap-2">
                                Processed sequentially.
                                <LemonButton
                                    onClick={openReorderModal}
                                    noPadding
                                    id="app-reorder"
                                    disabledReason={
                                        canConfigurePlugins
                                            ? undefined
                                            : 'You do not have permission to reorder plugins.'
                                    }
                                >
                                    Change order
                                </LemonButton>
                            </div>
                        </>
                    )}
                    <LemonTable
                        dataSource={displayablePluginConfigs}
                        size="xs"
                        loading={loading}
                        columns={[
                            {
                                title: 'Order',
                                key: 'order',
                                sticky: true,
                                render: function RenderOrdering(_, pluginConfig) {
                                    if (!pluginConfig.enabled) {
                                        return null
                                    }
                                    // We can't use pluginConfig.order directly as it's not nicely set for everything,
                                    // e.g. geoIP, disabled plugins, especially if we disable them via django admin
                                    return sortedEnabledPluginConfigs.findIndex((pc) => pc.id === pluginConfig.id) + 1
                                },
                            },
                            {
                                title: 'Name',
                                sticky: true,
                                render: function RenderPluginName(_, pluginConfig) {
                                    return (
                                        <>
                                            <Tooltip title="Click to update configuration, view metrics, and more">
                                                <Link
                                                    to={urls.pipelineApp(
                                                        PipelineAppKind.Transformation,
                                                        pluginConfig.id,
                                                        PipelineAppTab.Configuration
                                                    )}
                                                >
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
                                    return <RenderApp plugin={pluginConfig.plugin_info} />
                                },
                            },
                            updatedAtColumn() as LemonTableColumn<PluginConfigWithPluginInfoNew, any>,
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
                                    return <More overlay={<TransformationsMoreOverlay pluginConfig={pluginConfig} />} />
                                },
                            },
                        ]}
                    />
                </>
            )}
        </>
    )
}

export const TransformationsMoreOverlay = ({
    pluginConfig,
    inOverview = false,
}: {
    pluginConfig: PluginConfigWithPluginInfoNew
    inOverview?: boolean
}): JSX.Element => {
    const { canConfigurePlugins } = useValues(pipelineTransformationsLogic)
    const { openReorderModal, toggleEnabled, loadPluginConfigs } = useActions(pipelineTransformationsLogic)

    return (
        <>
            {!inOverview && (
                <LemonButton
                    onClick={() => {
                        toggleEnabled({
                            enabled: !pluginConfig.enabled,
                            id: pluginConfig.id,
                        })
                    }}
                    id={`app-${pluginConfig.id}-enable-switch`}
                    disabledReason={
                        canConfigurePlugins ? undefined : 'You do not have permission to enable/disable apps.'
                    }
                    fullWidth
                >
                    {pluginConfig.enabled ? 'Disable' : 'Enable'} app
                </LemonButton>
            )}
            {!inOverview && pluginConfig.enabled && (
                <LemonButton
                    onClick={openReorderModal}
                    id="app-reorder"
                    disabledReason={canConfigurePlugins ? undefined : 'You do not have permission to reorder apps.'}
                    fullWidth
                >
                    Reorder apps
                </LemonButton>
            )}
            <LemonButton
                to={urls.pipelineApp(PipelineAppKind.Transformation, pluginConfig.id, PipelineAppTab.Configuration)}
                id={`app-${pluginConfig.id}-configuration`}
                fullWidth
            >
                {canConfigurePlugins ? 'Edit' : 'View'} app configuration
            </LemonButton>
            <LemonButton
                to={urls.pipelineApp(PipelineAppKind.Transformation, pluginConfig.id, PipelineAppTab.Metrics)}
                id={`app-${pluginConfig.id}-metrics`}
                fullWidth
            >
                View app metrics
            </LemonButton>
            <LemonButton
                to={urls.pipelineApp(PipelineAppKind.Transformation, pluginConfig.id, PipelineAppTab.Logs)}
                id={`app-${pluginConfig.id}-logs`}
                fullWidth
            >
                View app logs
            </LemonButton>
            <LemonButton
                to={pluginConfig.plugin_info?.url}
                targetBlank={true}
                loading={!pluginConfig.plugin_info?.url}
                id={`app-${pluginConfig.id}-source-code`}
                fullWidth
            >
                View app source code
            </LemonButton>
            {!inOverview && (
                <>
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

function ReorderModal(): JSX.Element {
    const { reorderModalOpen, sortedEnabledPluginConfigs, temporaryOrder, pluginConfigsLoading } =
        useValues(pipelineTransformationsLogic)
    const { closeReorderModal, setTemporaryOrder, savePluginConfigsOrder } = useActions(pipelineTransformationsLogic)

    const handleDragEnd = ({ active, over }: DragEndEvent): void => {
        if (active.id && over && active.id !== over.id) {
            // Create new sortedEnabledPluginConfigs in the order after the move
            const from = sortedEnabledPluginConfigs.findIndex((config) => config.id === active.id)
            const to = sortedEnabledPluginConfigs.findIndex((config) => config.id === over.id)
            const newSortedEnabledPluginConfigs = arrayMove(sortedEnabledPluginConfigs, from, to)
            // Create new temporaryOrder by assinging pluginConfigIds to the index in the map of newSortedEnabledPluginConfigs
            // See comment in savePluginConfigsOrder about races
            const newTemporaryOrder = newSortedEnabledPluginConfigs.reduce((acc, pluginConfig, index) => {
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
                    <SortableContext items={sortedEnabledPluginConfigs} strategy={verticalListSortingStrategy}>
                        {sortedEnabledPluginConfigs.map((item, index) => (
                            <MinimalAppView key={item.id} pluginConfig={item} order={index} />
                        ))}
                    </SortableContext>
                </DndContext>
            </div>
        </LemonModal>
    )
}

const MinimalAppView = ({ pluginConfig, order }: { pluginConfig: PluginConfigTypeNew; order: number }): JSX.Element => {
    const { plugins } = useValues(pipelineTransformationsLogic)
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        id: pluginConfig.id,
    })

    const plugin = plugins[pluginConfig.plugin]
    return (
        <div
            ref={setNodeRef}
            className="flex gap-2 cursor-move border rounded p-2 items-center bg-bg-light"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                position: 'relative',
                transform: CSS.Transform.toString(transform),
                transition,
                zIndex: isDragging ? 999999 : undefined,
            }}
            {...attributes}
            {...listeners}
        >
            <LemonBadge.Number count={order + 1} maxDigits={3} />
            <PluginImage plugin={plugin} size="small" />
            <span className="font-semibold">{pluginConfig.name}</span>
        </div>
    )
}
