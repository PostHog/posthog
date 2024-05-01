import { useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { BatchExportService, PipelineStage, PluginType } from '~/types'

import { pipelineDestinationsLogic } from './destinationsLogic'
import { frontendAppsLogic } from './frontendAppsLogic'
import { PIPELINE_TAB_TO_NODE_STAGE } from './PipelineNode'
import { pipelineNodeNewLogic, PipelineNodeNewLogicProps } from './pipelineNodeNewLogic'
import { pipelineTransformationsLogic } from './transformationsLogic'
import { PipelineBackend } from './types'
import { getBatchExportUrl, RenderApp, RenderBatchExportIcon } from './utils'

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

type PluginEntry = {
    backend: PipelineBackend.Plugin
    id: number
    name: string
    description: string
    plugin: PluginType
    url?: string
}

type BatchExportEntry = {
    backend: PipelineBackend.BatchExport
    id: BatchExportService['type']
    name: string
    description: string
    url: string
}

type TableEntry = PluginEntry | BatchExportEntry

function convertPluginToTableEntry(plugin: PluginType): TableEntry {
    return {
        backend: PipelineBackend.Plugin,
        id: plugin.id,
        name: plugin.name,
        description: plugin.description || '',
        plugin: plugin,
        // TODO: ideally we'd link to docs instead of GitHub repo, so it can open in panel
        // Same for transformations and destinations tables
        url: plugin.url,
    }
}

function convertBatchExportToTableEntry(service: BatchExportService['type']): TableEntry {
    return {
        backend: PipelineBackend.BatchExport,
        id: service,
        name: service,
        description: `${service} batch export`,
        url: getBatchExportUrl(service),
    }
}

export function PipelineNodeNew(
    params: { stage?: string; pluginIdOrBatchExportDestination?: string } = {}
): JSX.Element {
    const { stage, pluginId, batchExportDestination } = paramsToProps({ params })
    const { batchExportServiceNames } = useValues(pipelineNodeNewLogic)

    if (!stage) {
        return <NotFound object="pipeline app stage" />
    }

    if (pluginId) {
        return <>Plugin ID {pluginId}</>
    }
    if (batchExportDestination) {
        if (stage !== PipelineStage.Destination) {
            return <NotFound object={batchExportDestination} />
        }
        return <>Batch Export Destination {batchExportDestination}</>
    }

    let targets: TableEntry[] = []
    let loadingAll = false
    if (stage === PipelineStage.Transformation) {
        // Show a list of transformations
        const { plugins, loading } = useValues(pipelineTransformationsLogic)
        loadingAll = loading
        targets = Object.values(plugins).map(convertPluginToTableEntry)
    } else if (stage === PipelineStage.Destination) {
        const { plugins, loading } = useValues(pipelineDestinationsLogic)
        loadingAll = loading
        const pluginTargets = Object.values(plugins).map(convertPluginToTableEntry)
        const batchExportTargets = Object.values(batchExportServiceNames).map(convertBatchExportToTableEntry)
        targets = [...batchExportTargets, ...pluginTargets]
    } else if (stage === PipelineStage.SiteApp) {
        const { plugins, loading } = useValues(frontendAppsLogic)
        targets = Object.values(plugins).map(convertPluginToTableEntry)
        loadingAll = loading
    }
    return nodeOptionsTable(stage, targets, loadingAll)
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
                        render: function RenderName(_, target) {
                            return (
                                <LemonTableLink
                                    to={target.url}
                                    target={target.backend == PipelineBackend.Plugin ? '_blank' : undefined}
                                    title={
                                        <>
                                            <Tooltip
                                                title={`Click to view ${
                                                    target.backend == PipelineBackend.Plugin
                                                        ? 'source code'
                                                        : 'documentation'
                                                }`}
                                            >
                                                <span>{target.name}</span>
                                            </Tooltip>
                                        </>
                                    }
                                    description={target.description}
                                />
                            )
                        },
                    },
                    {
                        title: 'App',
                        render: function RenderAppInfo(_, target) {
                            if (target.backend === PipelineBackend.Plugin) {
                                return <RenderApp plugin={target.plugin} />
                            }
                            return <RenderBatchExportIcon type={target.id} />
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
