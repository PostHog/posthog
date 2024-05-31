import { IconPlusSmall } from '@posthog/icons'
import { useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { NotFound } from 'lib/components/NotFound'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { AvailableFeature, BatchExportService, HogFunctionTemplateType, PipelineStage, PluginType } from '~/types'

import { pipelineDestinationsLogic } from './destinationsLogic'
import { frontendAppsLogic } from './frontendAppsLogic'
import { PipelineHogFunctionConfiguration } from './hogfunctions/PipelineHogFunctionConfiguration'
import { PipelineBatchExportConfiguration } from './PipelineBatchExportConfiguration'
import { PIPELINE_TAB_TO_NODE_STAGE } from './PipelineNode'
import { pipelineNodeNewLogic, PipelineNodeNewLogicProps } from './pipelineNodeNewLogic'
import { PipelinePluginConfiguration } from './PipelinePluginConfiguration'
import { pipelineTransformationsLogic } from './transformationsLogic'
import { PipelineBackend } from './types'
import { getBatchExportUrl, RenderApp, RenderBatchExportIcon } from './utils'

const paramsToProps = ({
    params: { stage, id },
}: {
    params: { stage?: string; id?: string }
}): PipelineNodeNewLogicProps => {
    const numericId = id && /^\d+$/.test(id) ? parseInt(id) : undefined
    const pluginId = numericId && !isNaN(numericId) ? numericId : null
    const hogFunctionId = pluginId ? null : id?.startsWith('hog-') ? id.slice(4) : null
    const batchExportDestination = hogFunctionId ? null : id ?? null

    return {
        stage: PIPELINE_TAB_TO_NODE_STAGE[stage + 's'] || null, // pipeline tab has stage plural here we have singular
        pluginId,
        batchExportDestination,
        hogFunctionId,
    }
}

export const scene: SceneExport = {
    component: PipelineNodeNew,
    logic: pipelineNodeNewLogic,
    paramsToProps,
}

type TableEntry = {
    backend: PipelineBackend
    id: string | number
    name: string
    description: string
    url?: string
    icon: JSX.Element
}

function convertPluginToTableEntry(plugin: PluginType): TableEntry {
    return {
        backend: PipelineBackend.Plugin,
        id: plugin.id,
        name: plugin.name,
        description: plugin.description || '',
        icon: <RenderApp plugin={plugin} />,
        // TODO: ideally we'd link to docs instead of GitHub repo, so it can open in panel
        // Same for transformations and destinations tables
        url: plugin.url,
    }
}

function convertBatchExportToTableEntry(service: BatchExportService['type']): TableEntry {
    return {
        backend: PipelineBackend.BatchExport,
        id: service as string,
        name: service,
        description: `${service} batch export`,
        icon: <RenderBatchExportIcon type={service} />,
        url: getBatchExportUrl(service),
    }
}

function convertHogFunctionToTableEntry(hogFunction: HogFunctionTemplateType): TableEntry {
    return {
        backend: PipelineBackend.HogFunction,
        id: `hog-${hogFunction.id}`, // TODO: This weird identifier thing isn't great
        name: hogFunction.name,
        description: hogFunction.description,
        icon: <span>🦔</span>,
    }
}

export function PipelineNodeNew(params: { stage?: string; id?: string } = {}): JSX.Element {
    const { stage, pluginId, batchExportDestination, hogFunctionId } = paramsToProps({ params })

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

    if (hogFunctionId) {
        const res = <PipelineHogFunctionConfiguration id={hogFunctionId} />
        if (stage === PipelineStage.Destination) {
            return <PayGateMini feature={AvailableFeature.DATA_PIPELINES}>{res}</PayGateMini>
        }
        return res
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
    const { plugins, loading, hogFunctionTemplates } = useValues(pipelineDestinationsLogic)
    const pluginTargets = Object.values(plugins).map(convertPluginToTableEntry)
    const batchExportTargets = Object.values(batchExportServiceNames).map(convertBatchExportToTableEntry)
    const hogFunctionTargets = Object.values(hogFunctionTemplates).map(convertHogFunctionToTableEntry)
    const targets = [...batchExportTargets, ...pluginTargets, ...hogFunctionTargets]
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
    const { hashParams } = useValues(router)
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
                            return target.icon
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
                                    // Preserve hash params to pass config in
                                    to={combineUrl(urls.pipelineNodeNew(stage, target.id), {}, hashParams).url}
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
