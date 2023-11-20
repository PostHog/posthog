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
import { pipelineTransformationsLogic } from './transformationsLogic'
import { PluginImage } from 'scenes/plugins/plugin/PluginImage'
import { PipelineAppTabs, PipelineTabs, PluginConfigTypeNew, PluginType, ProductKey } from '~/types'
import { urls } from 'scenes/urls'
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { DndContext, DragEndEvent } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { CSS } from '@dnd-kit/utilities'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { updatedAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { deleteWithUndo, humanFriendlyDetailedTime } from 'lib/utils'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown/LemonMarkdown'
import { dayjs } from 'lib/dayjs'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { NewButton } from './NewButton'

export function Transformations(): JSX.Element {
    const {
        loading,
        sortedEnabledPluginConfigs,
        disabledPluginConfigs,
        plugins,
        canConfigurePlugins,
        shouldShowProductIntroduction,
    } = useValues(pipelineTransformationsLogic)
    const { openReorderModal, toggleEnabled, loadPluginConfigs } = useActions(pipelineTransformationsLogic)

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
                    actionElementOverride={<NewButton tab={PipelineTabs.Transformations} />}
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
                                    type="tertiary"
                                    id={`app-reorder`}
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
                        dataSource={[...sortedEnabledPluginConfigs, ...disabledPluginConfigs]}
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
                                    return sortedEnabledPluginConfigs.findIndex((pc) => pc === pluginConfig) + 1
                                },
                            },
                            {
                                title: 'Name',
                                sticky: true,
                                render: function RenderPluginName(_, pluginConfig) {
                                    return (
                                        <>
                                            <Tooltip title={'Click to update configuration, view metrics, and more'}>
                                                <Link
                                                    to={urls.pipelineApp(
                                                        pluginConfig.id,
                                                        PipelineAppTabs.Configuration
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
                                    return <RenderApp plugin={plugins[pluginConfig.plugin]} />
                                },
                            },
                            updatedAtColumn() as LemonTableColumn<PluginConfigTypeNew, any>,
                            {
                                title: 'Status',
                                render: function RenderStatus(_, pluginConfig) {
                                    // We're not very good at cleaning up the errors, so let's not show it if more than 7 days have passed
                                    const days_since_error = pluginConfig.error
                                        ? dayjs().diff(dayjs(pluginConfig.error.time), 'day')
                                        : null
                                    const show_error: boolean = !(days_since_error && days_since_error < 7)
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
                                            {pluginConfig.error && show_error && (
                                                <>
                                                    <br />
                                                    <Tooltip
                                                        title={
                                                            <>
                                                                Click to see logs.
                                                                <br />
                                                                {humanFriendlyDetailedTime(
                                                                    pluginConfig.error.time
                                                                )}: {pluginConfig.error.message}
                                                            </>
                                                        }
                                                    >
                                                        <Link
                                                            to={urls.pipelineApp(pluginConfig.id, PipelineAppTabs.Logs)}
                                                        >
                                                            <LemonTag type="danger" className="uppercase">
                                                                Error
                                                            </LemonTag>
                                                        </Link>
                                                    </Tooltip>
                                                </>
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
                                                        status="stealth"
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
                                                    {pluginConfig.enabled && (
                                                        <LemonButton
                                                            status="stealth"
                                                            onClick={openReorderModal}
                                                            id={`app-reorder`}
                                                            disabledReason={
                                                                canConfigurePlugins
                                                                    ? undefined
                                                                    : 'You do not have permission to reorder apps.'
                                                            }
                                                            fullWidth
                                                        >
                                                            Reorder apps
                                                        </LemonButton>
                                                    )}
                                                    <LemonButton
                                                        status="stealth"
                                                        to={urls.pipelineApp(
                                                            pluginConfig.id,
                                                            PipelineAppTabs.Configuration
                                                        )}
                                                        id={`app-${pluginConfig.id}-configuration`}
                                                        fullWidth
                                                    >
                                                        {canConfigurePlugins ? 'Edit' : 'View'} app configuration
                                                    </LemonButton>
                                                    <LemonButton
                                                        status="stealth"
                                                        to={urls.pipelineApp(pluginConfig.id, PipelineAppTabs.Metrics)}
                                                        id={`app-${pluginConfig.id}-metrics`}
                                                        fullWidth
                                                    >
                                                        View app metrics
                                                    </LemonButton>
                                                    <LemonButton
                                                        status="stealth"
                                                        to={urls.pipelineApp(pluginConfig.id, PipelineAppTabs.Logs)}
                                                        id={`app-${pluginConfig.id}-logs`}
                                                        fullWidth
                                                    >
                                                        View app logs
                                                    </LemonButton>
                                                    {plugins[pluginConfig.plugin].url && (
                                                        <LemonButton
                                                            status="stealth"
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
                                                        id={`app-reorder`}
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
            )}
        </>
    )
}

type RenderAppProps = {
    plugin: PluginType
}

function RenderApp({ plugin }: RenderAppProps): JSX.Element {
    return (
        <div className="flex items-center gap-4">
            <Tooltip
                title={
                    <>
                        {plugin.name}
                        <br />
                        {plugin.description}
                        <br />
                        Click to view app source code
                    </>
                }
            >
                <Link to={plugin.url} target="_blank">
                    <PluginImage plugin={plugin} />
                </Link>
            </Tooltip>
        </div>
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
