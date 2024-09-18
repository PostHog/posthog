import { IconPlusSmall } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { NotFound } from 'lib/components/NotFound'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { useEffect } from 'react'
import { NewSourceWizardScene } from 'scenes/data-warehouse/new/NewSourceWizard'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { AvailableFeature, PipelineStage, PluginType } from '~/types'

import { NewDestinations } from './destinations/NewDestinations'
import { frontendAppsLogic } from './frontendAppsLogic'
import { HogFunctionConfiguration } from './hogfunctions/HogFunctionConfiguration'
import { PipelineBatchExportConfiguration } from './PipelineBatchExportConfiguration'
import { PIPELINE_TAB_TO_NODE_STAGE } from './PipelineNode'
import { pipelineNodeNewLogic, PipelineNodeNewLogicProps } from './pipelineNodeNewLogic'
import { PipelinePluginConfiguration } from './PipelinePluginConfiguration'
import { pipelineTransformationsLogic } from './transformationsLogic'
import { PipelineBackend } from './types'
import { RenderApp } from './utils'

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
        return <HogFunctionConfiguration templateId={hogFunctionId} />
    }

    if (stage === PipelineStage.Transformation) {
        return <TransformationOptionsTable />
    } else if (stage === PipelineStage.Destination) {
        return <NewDestinations />
    } else if (stage === PipelineStage.SiteApp) {
        return <SiteAppOptionsTable />
    } else if (stage === PipelineStage.Source) {
        return <NewSourceWizardScene />
    }
    return <NotFound object="pipeline new options" />
}

function TransformationOptionsTable(): JSX.Element {
    const { plugins, loading } = useValues(pipelineTransformationsLogic)
    const targets = Object.values(plugins).map(convertPluginToTableEntry)
    return <NodeOptionsTable stage={PipelineStage.Transformation} targets={targets} loading={loading} />
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
    const { loadPlugins } = useActions(pipelineNodeNewLogic)

    useEffect(() => {
        loadPlugins()
    }, [])

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
