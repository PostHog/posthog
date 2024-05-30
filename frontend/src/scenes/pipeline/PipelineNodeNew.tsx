import { IconPlusSmall } from '@posthog/icons'
import { useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { AvailableFeature, BatchExportService, PipelineStage, PluginType } from '~/types'

import { pipelineDestinationsLogic } from './destinationsLogic'
import { frontendAppsLogic } from './frontendAppsLogic'
import { PipelineBatchExportConfiguration } from './PipelineBatchExportConfiguration'
import { PIPELINE_TAB_TO_NODE_STAGE } from './PipelineNode'
import { pipelineNodeNewLogic, PipelineNodeNewLogicProps } from './pipelineNodeNewLogic'
import { PipelinePluginConfiguration } from './PipelinePluginConfiguration'
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

    if (!stage) {
        return <NotFound object="pipeline app stage" />
    }

    if (pluginId) {
        const res = <PipelinePluginConfiguration stage={stage} pluginId={pluginId} />
        if (stage === PipelineStage.Destination) {
            return <PayGateMini feature={AvailableFeature.DATA_PIPELINES}>{res}</PayGateMini>
        }
        return res
    }
    if (batchExportDestination) {
        if (stage !== PipelineStage.Destination) {
            return <NotFound object={batchExportDestination} />
        }
        return (
            <PayGateMini feature={AvailableFeature.DATA_PIPELINES}>
                <PipelineBatchExportConfiguration service={batchExportDestination} />
            </PayGateMini>
        )
    }

    if (stage === PipelineStage.Transformation) {
        return <TransformationOptionsTable />
    } else if (stage === PipelineStage.Destination) {
        return (
            <PayGateMini feature={AvailableFeature.DATA_PIPELINES}>
                <DestinationOptionsTable />
            </PayGateMini>
        )
    } else if (stage === PipelineStage.SiteApp) {
        return <SiteAppOptionsTable />
    }
    return <NotFound object="pipeline new options" />
}

function TransformationOptionsTable(): JSX.Element {
    const { plugins, loading } = useValues(pipelineTransformationsLogic)
    const targets = Object.values(plugins).map(convertPluginToTableEntry)
    return <NodeOptionsTable stage={PipelineStage.Transformation} targets={targets} loading={loading} />
}

function DestinationOptionsTable(): JSX.Element {
    const { batchExportServiceNames } = useValues(pipelineNodeNewLogic)
    const { plugins, loading } = useValues(pipelineDestinationsLogic)
    const pluginTargets = Object.values(plugins).map(convertPluginToTableEntry)
    const batchExportTargets = Object.values(batchExportServiceNames).map(convertBatchExportToTableEntry)
    const targets = [...batchExportTargets, ...pluginTargets]
    return <NodeOptionsTable stage={PipelineStage.Destination} targets={targets} loading={loading} />
}

function SiteAppOptionsTable(): JSX.Element {
    const { plugins, loading } = useValues(frontendAppsLogic)
    const targets = Object.values(plugins).map(convertPluginToTableEntry)
    return <NodeOptionsTable stage={PipelineStage.SiteApp} targets={targets} loading={loading} />
}

function NodeOptionsTable({
    stage,
    targets,
    loading,
}: {
    stage: PipelineStage
    targets: TableEntry[]
    loading: boolean
}): JSX.Element {
    return (
        <>
            <LemonTable
                dataSource={targets}
                size="small"
                loading={loading}
                columns={[
                    {
                        title: 'App',
                        width: 0,
                        render: function RenderAppInfo(_, target) {
                            if (target.backend === PipelineBackend.Plugin) {
                                return <RenderApp plugin={target.plugin} />
                            }
                            return <RenderBatchExportIcon type={target.id} />
                        },
                    },
                    {
                        title: 'Name',
                        sticky: true,
                        render: function RenderName(_, target) {
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
                        title: 'Actions',
                        width: 100,
                        align: 'right',
                        render: function RenderActions(_, target) {
                            return (
                                <LemonButton
                                    type="primary"
                                    data-attr={`new-${stage}-${target.id}`}
                                    icon={<IconPlusSmall />}
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
