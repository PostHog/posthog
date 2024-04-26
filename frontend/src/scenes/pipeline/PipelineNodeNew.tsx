import { useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { BatchExportService, PipelineStage, PluginType } from '~/types'

import { pipelineDestinationsLogic } from './destinationsLogic'
import { frontendAppsLogic } from './frontendAppsLogic'
import { PIPELINE_TAB_TO_NODE_STAGE } from './PipelineNode'
import { pipelineNodeNewLogic, PipelineNodeNewLogicProps } from './pipelineNodeNewLogic'
import { pipelineTransformationsLogic } from './transformationsLogic'
import { RenderApp, RenderBatchExportIcon } from './utils'

const paramsToProps = ({
    params: { stage, pluginIdOrBatchExportDestination },
}: {
    params: { stage?: string; pluginIdOrBatchExportDestination?: string }
}): PipelineNodeNewLogicProps => {
    const numericId =
        pluginIdOrBatchExportDestination && /^\d+$/.test(pluginIdOrBatchExportDestination)
            ? parseInt(pluginIdOrBatchExportDestination)
            : undefined
    const pluginId = numericId && !isNaN(numericId) ? numericId : null
    const batchExportDestination = pluginId ? null : pluginIdOrBatchExportDestination ?? null

    return {
        stage: PIPELINE_TAB_TO_NODE_STAGE[stage + 's'] || null, // pipeline tab has stage plural here we have singular
        pluginId: pluginId,
        batchExportDestination: batchExportDestination,
    }
}

export const scene: SceneExport = {
    component: PipelineNodeNew,
    logic: pipelineNodeNewLogic,
    paramsToProps,
}

interface PluginEntry {
    id: number
    name: string
    description: string | undefined
    plugin: PluginType
    service: null
}
interface BatchExportEntry {
    id: string
    name: string
    description: string | undefined
    plugin: null
    service: BatchExportService
}

type TableEntry = PluginEntry | BatchExportEntry

function convertPluginToTableEntry(plugin: PluginType): TableEntry {
    return {
        id: plugin.id,
        name: plugin.name,
        description: plugin.description,
        plugin: plugin,
        service: null,
    }
}

export function PipelineNodeNew(
    params: { stage?: string; pluginIdOrBatchExportDestination?: string } = {}
): JSX.Element {
    const { stage, pluginId, batchExportDestination } = paramsToProps({ params })

    if (!stage) {
        return <NotFound object="pipeline app stage" />
    }

    if (pluginId) {
        return <>Plugin ID {pluginId}</>
    }
    if (batchExportDestination) {
        return <>Batch Export Destination {batchExportDestination}</>
    }

    if (stage === PipelineStage.Transformation) {
        // Show a list of transformations
        const { plugins, loading } = useValues(pipelineTransformationsLogic)
        const targets = Object.values(plugins).map(convertPluginToTableEntry)
        return nodeOptionsTable(stage, targets, loading)
    } else if (stage === PipelineStage.Destination) {
        const { plugins, loading } = useValues(pipelineDestinationsLogic)
        // Show a list of destinations - TODO: add batch export destinations too
        const targets = Object.values(plugins).map(convertPluginToTableEntry)
        return nodeOptionsTable(stage, targets, loading)
    } else if (stage === PipelineStage.SiteApp) {
        const { plugins, loading } = useValues(frontendAppsLogic)
        const targets = Object.values(plugins).map(convertPluginToTableEntry)
        return nodeOptionsTable(stage, targets, loading)
    }
    return <>Creation is unavailable for {stage}</>
}

function nodeOptionsTable(stage: PipelineStage, targets: TableEntry[], loading: boolean): JSX.Element {
    return (
        <>
            <LemonTable
                dataSource={targets}
                size="small"
                loading={loading}
                columns={[
                    {
                        title: 'Name',
                        sticky: true,
                        render: function RenderPluginName(_, target) {
                            return (
                                <LemonTableLink
                                    to={urls.pipelineNodeNew(stage, target.id)}
                                    title={target.name}
                                    description={target.description}
                                />
                            )
                        },
                    },
                    {
                        title: 'App',
                        render: function RenderAppInfo(_, target) {
                            if (target.plugin) {
                                return <RenderApp plugin={target.plugin} />
                            }
                            return <RenderBatchExportIcon type={target.service.type} />
                        },
                    },
                    {
                        title: 'Actions',
                        width: 100,
                        align: 'right',
                        render: function RenderActions(_, target) {
                            return (
                                <LemonButton
                                    type="primary"
                                    data-attr={`new-${stage}-${target.id}`}
                                    to={urls.pipelineNodeNew(stage, target.id)}
                                >
                                    Create
                                </LemonButton>
                            )
                        },
                    },
                ]}
            />
        </>
    )
}
